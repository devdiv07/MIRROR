"""
Adjusted daily moves (ADR 0001 §5.1, §7; Milestone 3).

compute_move(conn, security_id, day, as_of=..., calendars=...) -> Move. It is deterministic and reads
only what was stored by `as_of`: bars from the newest import with imported_at <= as_of
(db.price_bars_as_of) and corporate actions with first_seen_at <= as_of. Nothing is written.

  r_D = close_raw(D) / (close_raw(D-1) / k_D) - 1, where k_D is the product of new_per_old over the
  split/bonus actions with ex_date = D. D-1 is the previous session in the exchange calendar.

Every result has a status, and only 'computed' presents a move:
  computed              move, trace and provenance
  held                  a move of >= 30% whose raw close ratio is within 2% of a common split ratio
                        (or its reciprocal): possible unrecorded corporate action; the card says
                        "check corporate actions" and shows no move
  stale                 the calendar expects a bar for D and there is none: "price as of <last day>"
  no_previous_close     no bar for the previous session; nothing is carried forward
  no_trade              the D bar has zero volume (possible suspension); no move
  missing_provenance    a bar needed for the move has no resolvable price_import; no number is shown
  market_closed         D is not a session
  calendar_not_covered  the calendar has no holiday list for D or the previous session

Deliberate choices beyond ADR §7 (recorded in the ADR's Milestone 3 amendment):
  - The guard also checks reciprocal ratios, so a reverse split (a move up) is held too.
  - adjustment_mismatch compares returns: |r_D - vendor r_D| > 0.5 percentage points.
  - calc_version is MOVES_VERSION plus a hash of PARAMS, not `git describe`. It changes when the
    formula or a parameter changes, not on every unrelated commit.
The benchmark-relative move (ADR §7) is left for Milestone 4, where cases A4 and R2 need it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from src.core.calendar import CalendarNotCovered, ExchangeCalendar
from src.sources.corporate_actions import ADJUSTING
from src.store import db

MOVES_VERSION = 'moves/1'
PARAMS = {
    'guard_min_abs_move': 0.30,
    'guard_ratios': [1.5, 2, 3, 4, 5, 10],
    'guard_tolerance': 0.02,
    'adjustment_mismatch_pp': 0.5,
    'volume_sessions': 20,
    'volume_min_sessions': 10,
}
CALC_VERSION = f"{MOVES_VERSION}+{db.sha256_json(PARAMS)[:8]}"


@dataclass(frozen=True)
class PriceSource:
    """One price_import that a number was derived from (ADR §5.1)."""
    import_id: int
    file_name: str
    file_sha256: str
    declared_vendor: str
    declared_source_url: str | None
    vendor_as_of: str | None
    imported_at: str

    @property
    def upstream_known(self) -> bool:
        return self.declared_vendor != 'unknown' or self.declared_source_url is not None


@dataclass
class Move:
    security_id: int
    session_date: str
    as_of: str
    status: str
    detail: str = ''
    calc_version: str = CALC_VERSION
    move: float | None = None                   # r_D as a fraction; None unless status == 'computed'
    close: float | None = None
    prev_close: float | None = None
    prev_date: str | None = None
    k: float = 1.0
    actions: list = field(default_factory=list)          # corporate_action rows on D that entered k or flags
    bar_imports: dict = field(default_factory=dict)      # trade_date -> import_id of every bar used
    sources: list = field(default_factory=list)          # PriceSource of every import used
    price_as_of: str | None = None                       # latest bar day <= D (the 'stale' card shows it)
    vendor_move: float | None = None
    volume_ratio: float | None = None
    volume_note: str | None = None                       # 'insufficient_history' | 'no_volume' | 'zero_median'
    flags: list = field(default_factory=list)

    @property
    def move_pct(self) -> float | None:
        return None if self.move is None else self.move * 100


def _source(bar) -> PriceSource:
    return PriceSource(bar['import_id'], bar['file_name'], bar['file_sha256'], bar['declared_vendor'],
                       bar['declared_source_url'], bar['vendor_as_of'], bar['imported_at'])


def _near_split_ratio(prev_close: float, close: float) -> bool:
    ratio = prev_close / close
    candidates = PARAMS['guard_ratios'] + [1 / c for c in PARAMS['guard_ratios']]
    return any(abs(ratio / c - 1) <= PARAMS['guard_tolerance'] for c in candidates)


def compute_move(conn, security_id: int, day: date, *, as_of: str,
                 calendars: dict[str, ExchangeCalendar]) -> Move:
    sec = conn.execute('SELECT exchange FROM security WHERE security_id = ?', (security_id,)).fetchone()
    cal = calendars[sec['exchange']]
    out = Move(security_id, day.isoformat(), as_of, 'computed')
    try:
        session = cal.session(day)
        prev = cal.previous_session(day) if session else None
    except CalendarNotCovered as e:
        out.status, out.detail = 'calendar_not_covered', str(e)
        return out
    if session is None:
        out.status, out.detail = 'market_closed', f"{cal.code} closed on {day} ({cal.closure_reason(day)})"
        return out
    close_utc = session.close_utc()
    if close_utc is not None and as_of < db.utc_iso(close_utc):
        raise ValueError(f"the {cal.code} session of {day} had not closed as of {as_of}")

    bars = db.price_bars_as_of(conn, security_id, as_of, through=day.isoformat())
    out.price_as_of = max(bars) if bars else None
    bar, prev_bar = bars.get(day.isoformat()), bars.get(prev.day.isoformat())
    if bar is None:
        out.status = 'stale'
        out.detail = f"price as of {out.price_as_of}" if out.price_as_of else 'no price data'
        return out
    if prev_bar is None:
        out.status = 'no_previous_close'
        out.detail = f"no bar for the previous session {prev.day}; nothing is carried forward"
        return out
    out.prev_date = prev.day.isoformat()
    for b in (prev_bar, bar):
        out.bar_imports[b['trade_date']] = b['import_id']
    if not (bar['provenance_ok'] and prev_bar['provenance_ok']):
        out.status, out.detail = 'missing_provenance', 'price data missing provenance'
        return out
    out.close, out.prev_close = bar['close_raw'], prev_bar['close_raw']
    if bar['volume'] == 0:
        out.status, out.detail = 'no_trade', 'zero volume on the session: possible suspension, no move computed'
        out.flags.append('no_trade_possible_suspension')
        out.sources = [_source(b) for b in (prev_bar, bar)]
        return out

    actions = db.corporate_actions_as_of(conn, security_id, as_of)
    for a in actions:
        if a['ex_date'] != day.isoformat():
            continue
        out.actions.append(a)
        if a['action_type'] in ADJUSTING:
            out.k *= a['new_per_old']
        elif a['action_type'] == 'dividend':
            out.flags.append(f"dividend_ex_date {a['cash_amount']:g} {a['currency']}")
        elif a['action_type'] == 'rights':
            out.flags.append('rights_ex_date')

    r = out.close / (out.prev_close / out.k) - 1
    if bar['close_vendor_adj'] is not None and prev_bar['close_vendor_adj'] is not None:
        out.vendor_move = bar['close_vendor_adj'] / prev_bar['close_vendor_adj'] - 1
        if abs(r - out.vendor_move) * 100 > PARAMS['adjustment_mismatch_pp']:
            out.flags.append('adjustment_mismatch')
    if abs(r) >= PARAMS['guard_min_abs_move'] and _near_split_ratio(out.prev_close, out.close):
        out.status = 'held'
        out.detail = 'check corporate actions: the close changed by a common split ratio'
        out.flags.append('possible_unrecorded_corporate_action')
    else:
        out.move = r

    used = {prev_bar['trade_date']: prev_bar, bar['trade_date']: bar}
    _volume_ratio(out, cal, day, bars, actions, used)
    out.sources = sorted({_source(b) for b in used.values()}, key=lambda s: s.import_id)
    return out


def _volume_ratio(out: Move, cal: ExchangeCalendar, day: date, bars: dict, actions, used: dict) -> None:
    """volume(D) / median(volume over the prior sessions), prior volumes scaled by the k of any
    split/bonus between them and D. Fewer than volume_min_sessions usable bars: no number."""
    if out.status != 'computed':
        return
    vol = used[day.isoformat()]['volume']
    if vol is None:
        out.volume_note = 'no_volume'
        return
    prior, probe = [], day
    for _ in range(PARAMS['volume_sessions']):
        try:
            probe = cal.previous_session(probe).day
        except CalendarNotCovered:
            break
        b = bars.get(probe.isoformat())
        if b is None or not b['provenance_ok'] or b['volume'] is None:
            continue
        scale = 1.0
        for a in actions:
            if a['action_type'] in ADJUSTING and probe.isoformat() < a['ex_date'] <= day.isoformat():
                scale *= a['new_per_old']
        prior.append(b['volume'] * scale)
        used[b['trade_date']] = b
        out.bar_imports[b['trade_date']] = b['import_id']
    if len(prior) < PARAMS['volume_min_sessions']:
        out.volume_note = 'insufficient_history'
        return
    median = statistics.median(prior)
    if median == 0:
        out.volume_note = 'zero_median'
        return
    out.volume_ratio = vol / median


def triggered(move: Move, trigger_pct: float | None) -> bool:
    """Whether the move earns a card: a computed |move| at or above the trigger, or a held move
    (which is shown as "check corporate actions", never as a move)."""
    if move.status == 'held':
        return True
    return move.status == 'computed' and trigger_pct is not None and abs(move.move_pct) >= trigger_pct


def _upstream_line(s: PriceSource) -> str:
    where = f"file {s.file_name}, sha256 {s.file_sha256[:12]}, imported {s.imported_at}"
    if not s.upstream_known:
        return f"Upstream price source: unknown (owner-supplied {where})"
    vendor = s.declared_vendor + (f" <{s.declared_source_url}>" if s.declared_source_url else '')
    return f"Upstream price source: {vendor} ({where}" + (f", vendor as of {s.vendor_as_of})" if s.vendor_as_of else ')')


def price_claim_lines(move: Move) -> list[str]:
    """The text of a move's price claims. A number appears only with its import, file hash,
    observation time and calculation trace (ADR §5.1); otherwise no number appears at all."""
    if move.status == 'missing_provenance':
        return ['price data missing provenance']
    if move.status in ('market_closed', 'calendar_not_covered', 'no_previous_close'):
        return [move.detail]
    if move.status == 'stale':
        return [f"stale: {move.detail}; no move computed"]
    lines = []
    if move.status == 'computed':
        lines.append(f"{move.move_pct:+.2f}% adjusted close-to-close ({move.prev_date} to {move.session_date})")
    elif move.status == 'held':
        lines.append('HELD: check corporate actions (the close changed by a common split ratio); no move is shown')
    else:
        lines.append(move.detail)
    imports = ', '.join(f"#{i}" for i in sorted(set(move.bar_imports.values())))
    lines.append(f"trace: close {move.close:,.2f} ({move.session_date}) vs {move.prev_close:,.2f} ({move.prev_date})"
                 f" ÷ k={move.k:g} · import {imports} · calc {move.calc_version}")
    if move.volume_ratio is not None:
        lines.append(f"volume {move.volume_ratio:.2f}× the median of the prior {PARAMS['volume_sessions']} sessions")
    elif move.volume_note:
        lines.append(f"volume ratio: {move.volume_note.replace('_', ' ')}")
    lines.extend(f"flag: {f}" for f in move.flags)
    lines.extend(_upstream_line(s) for s in move.sources)
    return lines
