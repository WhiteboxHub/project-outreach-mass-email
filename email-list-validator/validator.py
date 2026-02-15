import pandas as pd
import re
import dns.resolver
import logging
import argparse
import sys
from typing import List, Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("EmailListValidator")

class EmailListValidator:
    """
    Validates a list of emails for syntax and MX record existence.
    """
    
    EMAIL_REGEX = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.df = None
        self.domain_mx_cache = {}

    def load_data(self) -> None:
        """Loads email data from CSV file."""
        try:
            self.df = pd.read_csv(self.filepath)
            logger.info(f"Loaded {len(self.df)} rows from {self.filepath}")
        except Exception as e:
            logger.error(f"Failed to load file: {e}")
            raise

    def normalize_emails(self, column_name: str = 'email') -> None:
        """Normalizes email column by stripping whitespace and converting to lowercase."""
        if column_name not in self.df.columns:
            raise ValueError(f"Column '{column_name}' not found in CSV.")
            
        self.df[column_name] = self.df[column_name].astype(str).str.strip().str.lower()
        logger.info(f"Normalized '{column_name}' column.")

    def validate_syntax(self, column_name: str = 'email') -> None:
        """Validates email syntax using regex."""
        logger.info("Starting syntax validation...")
        self.df['syntax_valid'] = self.df[column_name].apply(
            lambda x: bool(re.match(self.EMAIL_REGEX, x))
        )
        valid_count = self.df['syntax_valid'].sum()
        logger.info(f"Syntax validation complete. {valid_count}/{len(self.df)} valid.")

    def _has_mx(self, domain: str) -> bool:
        """Checks if a domain has MX records."""
        if not domain:
            return False
            
        if domain in self.domain_mx_cache:
            return self.domain_mx_cache[domain]

        try:
            dns.resolver.resolve(domain, 'MX')
            self.domain_mx_cache[domain] = True
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout):
            self.domain_mx_cache[domain] = False
            return False
        except Exception as e:
            logger.warning(f"DNS check failed for {domain}: {e}")
            self.domain_mx_cache[domain] = False
            return False

    def validate_mx(self, column_name: str = 'email', max_workers: int = 20) -> None:
        """Validates MX records for generic domains using concurrent DNS lookups."""
        logger.info("Starting MX record validation...")
        
        # Extract domain
        self.df['domain'] = self.df[column_name].apply(
            lambda x: x.split('@')[-1] if isinstance(x, str) and '@' in x else None
        )

        # Get unique domains to minimize DNS queries
        unique_domains = self.df['domain'].dropna().unique()
        total_unique = len(unique_domains)
        logger.info(f"Checking DNS for {total_unique} unique domains with {max_workers} workers...")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Use ThreadPoolExecutor for concurrent DNS lookups
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_domain = {executor.submit(self._has_mx, domain): domain for domain in unique_domains}
            
            completed = 0
            for future in as_completed(future_to_domain):
                completed += 1
                if completed % 100 == 0:
                    logger.info(f"Processed {completed}/{total_unique} domains...")

        self.df['mx_valid'] = self.df['domain'].map(self.domain_mx_cache)
        
        mx_valid_count = self.df['mx_valid'].sum()
        logger.info(f"MX validation complete. {mx_valid_count} valid domains found.")

    def export_results(self, output_path: str) -> None:
        """Exports the validated DataFrame to a CSV file."""
        try:
            self.df.to_csv(output_path, index=False)
            logger.info(f"Results exported to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export results: {e}")
            raise

    def run(self, input_col: str = 'email', output_file: str = 'validated_emails.csv', workers: int = 20):
        """Executes the full validation pipeline."""
        self.load_data()
        self.normalize_emails(input_col)
        self.validate_syntax(input_col)
        self.validate_mx(input_col, max_workers=workers)
        self.export_results(output_file)
        
        # Summary
        total = len(self.df)
        valid_syntax = self.df['syntax_valid'].sum()
        valid_mx = self.df['mx_valid'].sum()
        fully_valid = len(self.df[(self.df['syntax_valid']) & (self.df['mx_valid'])])
        
        print("\n--- Validation Summary ---")
        print(f"Total Emails: {total}")
        print(f"Syntax Valid: {valid_syntax} ({(valid_syntax/total)*100:.1f}%)")
        print(f"MX Valid:     {valid_mx} ({(valid_mx/total)*100:.1f}%)")
        print(f"Fully Valid:  {fully_valid} ({(fully_valid/total)*100:.1f}%)")
        print(f"Output saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Validate email lists for syntax and MX records.")
    parser.add_argument("input_file", help="Path to the input CSV file.")
    parser.add_argument("--col", default="email", help="Name of the email column in CSV (default: 'email').")
    parser.add_argument("--output", default="validated_emails.csv", help="Path to save the output CSV.")
    parser.add_argument("--workers", type=int, default=50, help="Number of concurrent workers for DNS checks (default: 50).")
    
    args = parser.parse_args()
    
    validator = EmailListValidator(args.input_file)
    validator.run(input_col=args.col, output_file=args.output, workers=args.workers)

if __name__ == "__main__":
    main()
