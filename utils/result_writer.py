import os
import json
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger("outreach_service")

class ResultWriter:
    def __init__(self, base_dir: str = "output"):
        self.base_dir = base_dir

    def save_result(self, run_id: str, data: Dict[str, Any]):
        """
        Saves the execution result to output/<YYYY-MM-DD>/<run_id>.json
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            output_dir = os.path.join(self.base_dir, today)
            
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                logger.info(f"Created output directory: {output_dir}")

            filename = f"{run_id}.json"
            filepath = os.path.join(output_dir, filename)

            # JSON serialization helper for datetime objects
            def json_serial(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError (f"Type {type(obj)} not serializable")

            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4, default=json_serial)
            
            logger.info(f"Saved execution results to: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save execution results: {e}")
            return None
