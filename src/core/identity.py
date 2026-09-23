"""
Security identity and watchlist loading (ADR 0001 §6, Milestone 1).

A watchlist YAML (see config/watchlist.example.yaml) names each security by a
MIRROR-assigned stable `key` that never changes, plus attributes and a symbol
history. load_watchlist() applies it to the store in one transaction:

  - idempotent: loading the same file twice leaves every row identical;
  - symbol changes add a period; they never rename a row or move price/event history,
    because everything else hangs off security_id;
  - a thesis/horizon edit updates the item and is logged in `feedback`;
  - securities dropped from the file are deactivated, not deleted.

Identifier choices (recorded in ADR 0001 §6, Q6):
  - US: CIK is stored as company_id (needed for SEC ingestion) but is not the key,
    because one CIK can cover several listed share classes.
  - India (provisional): no issuer-level identifier is used yet. The NSE symbol lives
    in the symbol history, and the ISIN, if given, is a validated attribute, not the key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import yaml

from src.core.calendar import ExchangeCalendar
from src.store import db

_KEY_RE = re.compile(r'^[A-Z0-9][A-Z0-9:._-]*$')
_SYMBOL_RE = re.compile(r'^[A-Z0-9][A-Z0-9&._-]*$')
_ISIN_RE = re.compile(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')


class WatchlistError(ValueError):
    """The watchlist file is malformed or internally inconsistent."""


@dataclass(frozen=True)
class SymbolPeriod:
    symbol: str
    valid_from: date
    valid_to: date | None = None    # exclusive; None = current


@dataclass(frozen=True)
class SecuritySpec:
    key: str
    market: str
    exchange: str
    name: str
    currency: str
    timezone: str
    symbols: tuple[SymbolPeriod, ...]
    cik: str | None = None
    isin: str | None = None
    thesis: str | None = None
    horizon: str | None = None
    move_trigger_pct: float | None = None


@dataclass(frozen=True)
class Watchlist:
    securities: tuple[SecuritySpec, ...]
    default_move_trigger_pct: float | None = None


@dataclass
class LoadReport:
    securities: dict[str, str] = field(default_factory=dict)      # key -> inserted|updated|unchanged
    symbols: dict[str, list[str]] = field(default_factory=dict)   # key -> per-period status
    items: dict[str, str] = field(default_factory=dict)
    deactivated: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        statuses = (list(self.securities.values()) + list(self.items.values())
                    + [s for v in self.symbols.values() for s in v])
        return bool(self.deactivated) or any(s != 'unchanged' for s in statuses)


def isin_check_digit_ok(isin: str) -> bool:
    """ISO 6166 check digit: letters become numbers (A=10 ... Z=35), then a Luhn check over all digits."""
    digits = ''.join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _as_date(value, where: str) -> date:
    if isinstance(value, datetime):
        raise WatchlistError(f"{where}: expected a date, got a timestamp {value!r}")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise WatchlistError(f"{where}: expected YYYY-MM-DD, got {value!r}") from e


def _optional_text(value, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WatchlistError(f"{where}: expected text")
    value = value.strip()
    return value or None


def _trigger(value, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise WatchlistError(f"{where}: move_trigger_pct must be a positive number")
    return float(value)


def _parse_symbols(raw, where: str) -> tuple[SymbolPeriod, ...]:
    if not isinstance(raw, list) or not raw:
        raise WatchlistError(f"{where}: 'symbols' must be a non-empty list")
    periods = []
    for i, p in enumerate(raw):
        w = f"{where}.symbols[{i}]"
        if not isinstance(p, dict) or 'symbol' not in p or 'valid_from' not in p:
            raise WatchlistError(f"{w}: needs 'symbol' and 'valid_from'")
        symbol = str(p['symbol']).strip()
        if not _SYMBOL_RE.match(symbol):
            raise WatchlistError(f"{w}: symbol {symbol!r} must be upper-case letters/digits (& . _ - allowed)")
        vf = _as_date(p['valid_from'], w)
        vt = _as_date(p['valid_to'], w) if p.get('valid_to') is not None else None
        if vt is not None and vt <= vf:
            raise WatchlistError(f"{w}: valid_to must be after valid_from")
        periods.append(SymbolPeriod(symbol, vf, vt))
    periods.sort(key=lambda p: p.valid_from)
    for earlier, later in zip(periods, periods[1:]):
        if earlier.valid_to is None or earlier.valid_to > later.valid_from:
            raise WatchlistError(
                f"{where}: symbol periods {earlier.symbol} (from {earlier.valid_from}) and "
                f"{later.symbol} (from {later.valid_from}) overlap; set valid_to on the earlier one")
    return tuple(periods)


def parse_watchlist(path: str, calendars: dict[str, ExchangeCalendar]) -> Watchlist:
    """Read and validate a watchlist YAML. Market, currency and timezone come from the exchange config."""
    with open(path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or cfg.get('version') != 1:
        raise WatchlistError(f"{path}: expected a mapping with 'version: 1'")
    defaults = cfg.get('defaults') or {}
    default_trigger = _trigger(defaults.get('move_trigger_pct'), f"{path}: defaults")
    raw = cfg.get('securities')
    if not isinstance(raw, list) or not raw:
        raise WatchlistError(f"{path}: 'securities' must be a non-empty list")

    specs, seen = [], set()
    for i, s in enumerate(raw):
        where = f"{path}: securities[{i}]"
        if not isinstance(s, dict):
            raise WatchlistError(f"{where}: expected a mapping")
        key = str(s.get('key', '')).strip()
        if not _KEY_RE.match(key):
            raise WatchlistError(f"{where}: key {key!r} must be upper-case, e.g. 'IN:NSE:ABC'")
        if key in seen:
            raise WatchlistError(f"{where}: duplicate key {key!r}")
        seen.add(key)
        where = f"{path}: {key}"

        exchange = str(s.get('exchange', '')).strip()
        cal = calendars.get(exchange)
        if cal is None:
            raise WatchlistError(f"{where}: exchange {exchange!r} is not in config/exchanges.yaml "
                                 f"({sorted(calendars)})")
        name = _optional_text(s.get('name'), where)
        if not name:
            raise WatchlistError(f"{where}: 'name' is required")

        cik = s.get('cik')
        if cal.market == 'US':
            if cik is None or not re.fullmatch(r'\d{1,10}', str(cik).strip()):
                raise WatchlistError(f"{where}: US securities need 'cik' (up to 10 digits, from SEC)")
            cik = str(cik).strip().zfill(10)
        elif cik is not None:
            raise WatchlistError(f"{where}: 'cik' only applies to US securities")

        isin = _optional_text(s.get('isin'), where)
        if isin is not None:
            isin = isin.upper()
            if not _ISIN_RE.match(isin) or not isin_check_digit_ok(isin):
                raise WatchlistError(f"{where}: isin {isin!r} is not a valid ISIN (format or check digit)")
            if cal.market == 'IN' and not isin.startswith('IN'):
                raise WatchlistError(f"{where}: an NSE equity ISIN should start with 'IN'")

        specs.append(SecuritySpec(
            key=key, market=cal.market, exchange=exchange, name=name,
            currency=cal.currency, timezone=cal.tz.key,
            symbols=_parse_symbols(s.get('symbols'), where),
            cik=cik, isin=isin,
            thesis=_optional_text(s.get('thesis'), where),
            horizon=_optional_text(s.get('horizon'), where),
            move_trigger_pct=_trigger(s.get('move_trigger_pct'), where),
        ))
    return Watchlist(tuple(specs), default_trigger)


def _utc_stamp(now: datetime | None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    return now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_watchlist(conn, watchlist: Watchlist, now: datetime | None = None) -> LoadReport:
    """Apply a parsed watchlist to the store atomically. Raises db.IdentityConflict on history conflicts."""
    stamp = _utc_stamp(now)
    report = LoadReport()
    with db.transaction(conn):
        kept: set[int] = set()
        for spec in watchlist.securities:
            sid, status = db.upsert_security(
                conn, security_key=spec.key, market=spec.market, exchange=spec.exchange,
                name=spec.name, currency=spec.currency, timezone=spec.timezone,
                company_id_type='CIK' if spec.cik else None, company_id=spec.cik,
                isin=spec.isin, now=stamp)
            report.securities[spec.key] = status
            report.symbols[spec.key] = [
                db.upsert_symbol_period(conn, security_id=sid, exchange=spec.exchange,
                                        symbol=p.symbol, valid_from=p.valid_from, valid_to=p.valid_to)
                for p in spec.symbols
            ]
            report.items[spec.key] = db.upsert_watchlist_item(
                conn, security_id=sid, thesis=spec.thesis, horizon=spec.horizon,
                move_trigger_pct=spec.move_trigger_pct, now=stamp)
            kept.add(sid)
        db.check_symbol_invariants(conn)
        report.deactivated = db.deactivate_items_except(conn, kept, stamp)
    return report
