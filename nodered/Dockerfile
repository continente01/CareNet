FROM nodered/node-red:latest

# Switch to root to install extra nodes
USER root

# Use the Node-RED user directory (inside container it's /data)
WORKDIR /data

# Copy package.json and install extra nodes (like dashboard)
COPY package.json .
RUN npm install --unsafe-perm --no-audit --no-fund --only=production

# Copy your predefined flows
COPY flows.json /data/flows.json

# Reset workdir back to Node-RED app dir so entrypoint.sh works
WORKDIR /usr/src/node-red

# Switch back to node-red user
USER node-red

EXPOSE 1880
