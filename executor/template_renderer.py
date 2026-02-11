from jinja2 import Environment, BaseLoader, StrictUndefined, Template, meta
from typing import Dict, Any, Set, List
import logging

logger = logging.getLogger("outreach_service")

class TemplateRenderer:
    def __init__(self):
        # StrictUndefined raises an error if a variable is missing
        self.env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._template_cache: Dict[str, Template] = {}

    def _get_template(self, template_str: str) -> Template:
        """
        Retrieves a compiled template from cache or compiles it.
        """
        if template_str not in self._template_cache:
            self._template_cache[template_str] = self.env.from_string(template_str)
        return self._template_cache[template_str]

    def validate(self, template_str: str, context: Dict[str, Any]) -> List[str]:
        """
        Validates if all variables in the template are present in the context.
        Returns a list of missing variables.
        """
        try:
            # Parse the AST to find undeclared variables
            ast = self.env.parse(template_str)
            required_vars = meta.find_undeclared_variables(ast)
            
            missing_vars = [var for var in required_vars if var not in context]
            return missing_vars
        except Exception as e:
            logger.error(f"Template validation failed: {e}")
            # If we can't parse, we assume it's unsafe or invalid syntax
            return [f"Template Syntax Error: {str(e)}"]

    def render(self, template_str: str, context: Dict[str, Any]) -> str:
        """Renders a string template with the provided context."""
        if not template_str:
            return ""
        try:
            template = self._get_template(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            raise ValueError(f"Template rendering failed: {e}")
