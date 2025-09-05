

def moving_average(data, window_size):
    if not data or window_size <= 0:
        return []

    moving_averages = []
    for i in range(len(data) - window_size + 1):
        window = data[i:i + window_size]
        window_average = sum(window) / window_size
        moving_averages.append(window_average)

    return moving_averages

# Example usage
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
window_size = 3
print(moving_average(data, window_size))


