from sklearn.cluster import KMeans
import numpy as np

# Example data
data = np.array([1,3,4,6,7,8,9,10,12,13,14,15]).reshape(-1, 1)
print(data)
# Reshape the data to be 2D for KMeans

# Fit the KMeans model
n_clusters = 2
random_state = 0
kmeans = KMeans(n_clusters=n_clusters, random_state=random_state).fit(data)

# Predict the clusters
labels = kmeans.predict(data)

# Print the cluster centers and labels
print("Cluster centers:\n", kmeans.cluster_centers_)
print("Labels:", labels)

print("Data points with their respective cluster labels:")
for point, label in zip(data, labels):
    print(f"Point: {point}, Cluster: {label}")

# Label a new point
new_point = np.array([[17]])
new_label = kmeans.predict(new_point)

print(f"New point: {new_point[0][0]}, Cluster: {new_label[0]}")

# Label a new point
new_point = np.array([[5]])
new_label = kmeans.predict(new_point)

print(f"New point: {new_point[0][0]}, Cluster: {new_label[0]}")