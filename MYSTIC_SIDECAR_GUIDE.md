# Gnosis Mystic Sidecar Deployment Guide

This guide explains how to deploy Gnosis Mystic as a sidecar container alongside your application, using gnosis-ocr as an example.

## Overview

The sidecar pattern allows Mystic to run alongside your application container, providing:
- Function hijacking and performance optimization without modifying application code
- Complete isolation between application and debugging logic
- Easy enable/disable through environment variables
- Seamless integration with Claude Desktop via MCP

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   OCR Application   │────▶│   Mystic Sidecar    │────▶│   Claude Desktop    │
│   (Port 7799)       │     │   (Port 8899)       │     │   (MCP Client)      │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
         │                           │                            │
         └───────────────────────────┴────────────────────────────┘
                        Shared Network & Volumes
```

## Quick Start

### 1. Add Mystic Files to Your Project

Copy these files to your project:
- `docker-compose.mystic.yml` - Extended Docker Compose with Mystic
- `Dockerfile.mystic` - Mystic container image
- `mystic_server.py` - Mystic server implementation
- `app/mystic_integration.py` - Integration helpers for your app

### 2. Initialize Mystic Configuration

```bash
# Create Mystic configuration directory
mkdir -p .mystic

# Create initial config
cat > .mystic/config.json << EOF
{
  "project_name": "gnosis-ocr",
  "project_root": "/app",
  "ignore_patterns": ["*.pyc", "__pycache__", ".git", ".venv"],
  "auto_discover": true,
  "mcp_enabled": true
}
EOF
```

### 3. Start Services with Mystic

```bash
# Use the Mystic-enabled compose file
docker-compose -f docker-compose.mystic.yml up -d

# Check services are running
docker-compose -f docker-compose.mystic.yml ps

# View logs
docker-compose -f docker-compose.mystic.yml logs -f mystic
```

### 4. Configure Claude Desktop

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "gnosis-ocr-mystic": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--network", "gnosis-ocr_gnosis-network",
        "--env", "MYSTIC_HOST=mystic",
        "--env", "MYSTIC_PORT=8899",
        "--env", "PROJECT_ROOT=/app",
        "-v", "${PWD}/app:/app:ro",
        "gnosis-ocr_mystic-mcp"
      ]
    }
  }
}
```

## Integration Options

### Option 1: Transparent Integration (Recommended)

Add the `@mystic_aware` decorator to functions you want to monitor:

```python
from app.mystic_integration import mystic_aware

@mystic_aware
async def process_ocr(image_data: bytes) -> dict:
    # Your existing OCR logic
    result = await ocr_model.process(image_data)
    return result
```

### Option 2: Manual Integration

For more control, use the Mystic client directly:

```python
from app.mystic_integration import mystic_client

async def process_with_cache(data):
    # Check cache first
    cached = await mystic_client.get_cache("process_data", str(data))
    if cached:
        return cached
    
    # Process normally
    result = expensive_processing(data)
    
    # Store in cache
    await mystic_client.set_cache("process_data", str(data), result)
    
    return result
```

### Option 3: Environment-Based Behavior

Use environment variables to control behavior:

```python
import os

if os.getenv("MYSTIC_ENABLED") == "true":
    # Use optimized version
    from app.mystic_integration import mystic_aware
    process_function = mystic_aware(original_function)
else:
    # Use original version
    process_function = original_function
```

## Using Mystic Features

### 1. Function Discovery

In Claude Desktop:
```
"Discover all functions in the OCR project"
```

### 2. Add Caching

```
"Add caching to the process_ocr function for 30 minutes"
```

### 3. Mock External Services

```
"Mock the external API calls in development environment"
```

### 4. Performance Analysis

```
"Show me the slowest functions in the OCR service"
```

### 5. Security Filtering

```
"Add logging to all functions but filter out sensitive data"
```

## Environment Variables

### Application Container

```yaml
environment:
  - MYSTIC_ENABLED=true           # Enable Mystic integration
  - MYSTIC_HOST=mystic           # Mystic sidecar hostname
  - MYSTIC_PORT=8899             # Mystic API port
```

### Mystic Container

```yaml
environment:
  - MYSTIC_PORT=8899             # API server port
  - MYSTIC_HOST=0.0.0.0          # Bind to all interfaces
  - PROJECT_ROOT=/app            # Application root directory
  - LOG_LEVEL=INFO               # Logging level
  - MYSTIC_MODE=server           # Operation mode
```

## Production Deployment

### 1. Use Specific Versions

```dockerfile
# Instead of cloning from git
RUN pip install gnosis-mystic==1.0.0
```

### 2. Configure Resource Limits

```yaml
mystic:
  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 512M
      reservations:
        cpus: '0.25'
        memory: 256M
```

### 3. Add Health Checks

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8899/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

### 4. Use Secrets for Sensitive Data

```yaml
secrets:
  mystic_api_key:
    external: true

environment:
  - MYSTIC_API_KEY_FILE=/run/secrets/mystic_api_key
```

## Monitoring & Debugging

### View Mystic Logs

```bash
docker-compose -f docker-compose.mystic.yml logs -f mystic
```

### Check Hijacked Functions

```bash
curl http://localhost:8899/api/hijacked
```

### View Function Metrics

```bash
curl http://localhost:8899/api/metrics
```

### Interactive Shell

```bash
docker-compose -f docker-compose.mystic.yml exec mystic bash
```

## Troubleshooting

### Issue: Mystic not connecting to application

1. Check network connectivity:
```bash
docker-compose -f docker-compose.mystic.yml exec mystic ping app
```

2. Verify environment variables:
```bash
docker-compose -f docker-compose.mystic.yml exec app env | grep MYSTIC
```

### Issue: Functions not being discovered

1. Check file permissions:
```bash
docker-compose -f docker-compose.mystic.yml exec mystic ls -la /app
```

2. Verify Python path:
```bash
docker-compose -f docker-compose.mystic.yml exec mystic python -c "import sys; print(sys.path)"
```

### Issue: Claude Desktop not connecting

1. Check MCP server is running:
```bash
docker ps | grep mystic-mcp
```

2. Test MCP connection:
```bash
docker run --rm -it --network gnosis-ocr_gnosis-network \
  gnosis-ocr_mystic-mcp python -c "print('MCP test successful')"
```

## Advanced Patterns

### 1. Multi-Stage Hijacking

```python
# Development: Use mocks
# Staging: Use cache with short TTL
# Production: Use cache with long TTL
```

### 2. Circuit Breaker Pattern

```python
@mystic_aware
async def external_api_call():
    # Mystic can implement circuit breaker
    # to prevent cascading failures
    pass
```

### 3. A/B Testing

```python
# Mystic can route certain percentage
# of calls to different implementations
```

### 4. Gradual Rollout

```python
# Use Mystic to gradually roll out
# new function implementations
```

## Best Practices

1. **Start Small**: Begin with a few critical functions
2. **Monitor Impact**: Watch for performance overhead
3. **Use in Development First**: Test thoroughly before production
4. **Document Hijacked Functions**: Keep track of optimizations
5. **Regular Cleanup**: Remove unused hijacks
6. **Security First**: Never log sensitive data

## Next Steps

1. Explore the [Mystic Documentation](https://github.com/gnosis/gnosis-mystic)
2. Try different hijacking strategies
3. Build custom strategies for your use case
4. Contribute improvements back to the project

---

With this setup, you can now use Claude Desktop to intelligently optimize and debug your containerized applications without modifying any source code!
