from ContextAware import ContextAware

mcp = ContextAware()

# Register all default tools
mcp.register_default(all=True)

# Register a custom tool using the decorator
@mcp.tool(name="greet", description="Greet a user by name")
def greet(name="World"):
    return f"Hello, {name}!"

@mcp.tool(name='run_cli', description="Run a CLI command")
def run_cli(command):
    import subprocess
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout

# List all tools
print("Registered tools:", mcp.list_tools())

# View capabilities (JSON format)
import json
print("\nCapabilities (JSON):")
print(json.dumps(mcp.get_capabilities(), indent=2))

mcp.start_server()
while True:
    pass