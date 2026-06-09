n = int(input("Enter a number: "))
count = 0
num = n
while num > 0:
    count += 1
    num //= 10
    print("Number of digits in", n, "is", count)