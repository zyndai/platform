from DefaultTools import default_tools
from flask import Flask, request, jsonify
import threading
import inspect
import re
from hashlib import sha256
import hmac
import os

class ContextAware:
    def __init__(self):
        self.tools = {}
        self.token = None
        self.security()

    def security(self, token=None, disable = False):
        """Enable security for the MCP server."""
        if token:
            print("Passing token is not recommended. only do if you know what youre doing!")
            print("Generating a token is recommended. Use 'python -m ContextAware generate_token' to generate a token.")
            self.token = token
            print("Token set to:", self.token)
            return
        if disable:
            self.token = None
            print("Security disabled. NOT RECOMMENDED!")
            return
        
        print("Generating API KEY. Use this to call the MCP server")
        self.token = sha256(os.urandom(16)).hexdigest()
        print("API KEY:", self.token)
        return self.token

    def tool(self, name=None, description=None):
        """Decorator to register a function as a tool."""
        def decorator(func):
            tool_name = name or func.__name__
            self.tools[tool_name] = {
                "func": func,
                "description": description or (func.__doc__ or "").strip(),
                "schema": self._generate_schema(func),
            }
            return func
        return decorator

    def register(self, func, name=None, description=None):
        """Register a function as a tool directly (non-decorator)."""
        tool_name = name or func.__name__
        self.tools[tool_name] = {
            "func": func,
            "description": description or (func.__doc__ or "").strip(),
            "schema": self._generate_schema(func),
        }

    def register_default(self, names=None, all=False):
        """Register default built-in tools.

        Args:
            names (list): List of tool function names to register
            all (bool): If True, register all default tools
        """
        if all:
            for func in default_tools:
                self.register(func)
        elif names:
            tools_by_name = {f.__name__: f for f in default_tools}
            for name in names:
                if name in tools_by_name:
                    self.register(tools_by_name[name])
                else:
                    available = list(tools_by_name.keys())
                    raise ValueError(f"Unknown default tool '{name}'. Available: {available}")

    @staticmethod
    def _parse_param_descriptions(docstring):
        """Extract parameter descriptions from a Google-style docstring."""
        param_descs = {}
        if not docstring:
            return param_descs
        # Match lines like:  param_name (type): Description text
        #                or: param_name: Description text
        for match in re.finditer(
            r"^\s+(?:Args:)?\s*\n?",
            docstring,
            re.MULTILINE,
        ):
            pass  # just skip the Args: header
        for match in re.finditer(
            r"^\s{4,}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$",
            docstring,
            re.MULTILINE,
        ):
            param_descs[match.group(1)] = match.group(2).strip()
        return param_descs

    def _generate_schema(self, func):
        """Generate a parameter schema with descriptions from the function signature and docstring."""
        sig = inspect.signature(func)
        docstring = func.__doc__ or ""
        param_descs = self._parse_param_descriptions(docstring)
        params = {}

        for param_name, param in sig.parameters.items():
            param_info = {"required": param.default is inspect.Parameter.empty}

            # Infer type from default value if available
            if param.default is not inspect.Parameter.empty:
                param_info["default"] = param.default
                param_info["type"] = type(param.default).__name__
            else:
                param_info["type"] = "string"

            # Infer type from annotation if available
            if param.annotation is not inspect.Parameter.empty:
                param_info["type"] = param.annotation.__name__ if hasattr(param.annotation, '__name__') else str(param.annotation)

            # Add description from docstring if available
            if param_name in param_descs:
                param_info["description"] = param_descs[param_name]

            params[param_name] = param_info

        return {"parameters": params}

    @staticmethod
    def _extract_summary(docstring):
        """Extract just the summary line from a docstring (before Args/Returns)."""
        if not docstring:
            return ""
        lines = docstring.strip().splitlines()
        summary_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith(("args:", "returns:", "raises:", "yields:", "examples:", "note:")):
                break
            summary_lines.append(stripped)
        return " ".join(summary_lines).strip()

    def get_capabilities(self):
        """Return tool info in an LLM-friendly serializable format."""
        tools_list = []
        for name, tool in self.tools.items():
            tool_entry = {
                "name": name,
                "description": self._extract_summary(tool["description"]),
            }
            params_list = []
            for pname, pinfo in tool["schema"]["parameters"].items():
                param_entry = {
                    "name": pname,
                    "type": pinfo.get("type", "string"),
                    "required": pinfo.get("required", True),
                }
                if "default" in pinfo:
                    param_entry["default"] = pinfo["default"]
                if "description" in pinfo:
                    param_entry["description"] = pinfo["description"]
                params_list.append(param_entry)
            tool_entry["parameters"] = params_list
            tools_list.append(tool_entry)
        return {"tools": tools_list}

    def get_tools_prompt(self):
        """Return a plain-text description of all tools, formatted for LLM system prompts."""
        caps = self.get_capabilities()
        lines = ["You have access to the following tools:", ""]
        for tool in caps["tools"]:
            lines.append(f"## {tool['name']}")
            lines.append(f"{tool['description']}")
            if tool["parameters"]:
                lines.append("Parameters:")
                for p in tool["parameters"]:
                    parts = [f"  - {p['name']} ({p['type']})"]
                    if p.get("description"):
                        parts.append(f": {p['description']}")
                    if not p["required"]:
                        default_val = repr(p['default']) if 'default' in p else 'N/A'
                        parts.append(f" (optional, default={default_val})")
                    else:
                        parts.append(" [required]")
                    lines.append("".join(parts))
            else:
                lines.append("Parameters: None")
            lines.append("")
        return "\n".join(lines)

    def _call(self, name, params=None, token=None):
        """Call a registered tool by name.

        Args:
            name (str): Tool name
            params (dict): Parameters to pass to the tool

        Returns:
            The tool's return value
        """
        if name not in self.tools:
            available = list(self.tools.keys())
            raise ValueError(f"Tool '{name}' not found. Available: {available}")

        params = params or {}
        return self.tools[name]["func"](**params)

    def list_tools(self):
        """Return a simple list of registered tool names."""
        return list(self.tools.keys())

    def start_server(self, host="127.0.0.1", port=5000):
        """Start the Flask server in a background thread."""
        app = Flask(__name__)

        @app.route('/capabilities', methods=['GET'])
        def capabilities():
            return jsonify(self.get_capabilities())
        
        @app.route('/tools_prompt', methods=['GET'])
        def tools_prompt():
            return jsonify(self.get_tools_prompt())

        @app.route('/tools', methods=['GET'])
        def tools():
            return jsonify({"tools": self.list_tools()})

        @app.route('/call_tool', methods=['POST'])
        def call_tool():
            data = request.json
            if not data or 'name' not in data:
                return jsonify({"error": "Missing 'name' in request body"}), 400

            name = data['name']
            params = data.get('params', {})
            api_key = data.get('api_key')

            if self.token is not None:
                if not hmac.compare_digest(self.token, api_key):
                    return jsonify({"error": "Invalid API key"}), 401

            try:
                result = self._call(name, params)
                return jsonify({"result": result})
            except ValueError as e:
                return jsonify({"error": str(e)}), 404
            except TypeError as e:
                return jsonify({"error": f"Invalid parameters: {str(e)}"}), 400
            except Exception as e:
                return jsonify({"error": f"Tool execution failed: {str(e)}"}), 500

        def run_app():
            app.run(host=host, port=port, threaded=True, use_reloader=False)

        server_thread = threading.Thread(target=run_app)
        server_thread.daemon = True
        server_thread.start()

        return server_thread