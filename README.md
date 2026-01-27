# SWEMLS Coursework 3

## Simulator Setup

### Building the Simulator

To build the simulator Docker image:

```bash
docker build -t simulator ./simulator
```

### Running the Simulator

To start the simulator for testing:

```bash
docker run -p 8440:8440 -p 8441:8441 simulator
```

This will:
- Expose the MLLP server on ports 8440 and 8441
- Use the default messages from `messages.mllp`

### Additional Options

**Run in detached mode (background):**
```bash
docker run -d -p 8440:8440 -p 8441:8441 simulator
```

**Use custom messages file:**
```bash
docker run -p 8440:8440 -p 8441:8441 -v /path/to/messages.mllp:/data/messages.mllp simulator
```

**Stop a detached container:**
```bash
docker ps  # Find the container ID
docker stop <container_id>
```
