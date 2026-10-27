# Sandboxed test/command runner for GraphAgent Lab agent workspaces.
# Workspaces are bind-mounted at /work; agents run pytest or shell commands
# inside this container when Docker isolation is active.
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest

WORKDIR /work
CMD ["bash"]
