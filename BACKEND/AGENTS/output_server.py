import os
import pandas as pd
import uuid
from datetime import datetime

# Update this path to match your GTK installation directory
gtk_path = r'C:\Program Files\GTK3-Runtime Win64\bin'
if gtk_path not in os.environ['PATH']:
    os.environ['PATH'] = gtk_path + os.pathsep + os.environ['PATH']

from weasyprint import HTML
from typing import Set, Dict, Any

class OutputServer:
    def __init__(self):
        self.export_dir = "exports"
        os.makedirs(self.export_dir, exist_ok=True)

    def generate_file(self, data, format_type: str) -> str:
        """
        Receives leads data and generates the requested file format.
        Data can be either:
        - List[Dict]: list of lead records from DB (new format)
        - Dict: legacy format with sets of emails/companies/urls
        Returns the absolute path to the generated file.
        """
        # Handle both list and dict formats
        if isinstance(data, list):
            # New format: list of lead records from DB
            leads = []
            for record in data:
                leads.append({
                    "Company Name": record.get("company_name", "N/A"),
                    "Email Address": record.get("email", "N/A"),
                    "Source/Contact URL": record.get("source_url", "N/A")
                })
        else:
            # Legacy format: dict with sets
            emails = data.get("emails", set())
            companies = data.get("companies", set())
            urls = data.get("urls", set())
            
            max_len = max(len(emails), len(companies), len(urls))
            email_list = list(emails)
            company_list = list(companies)
            url_list = list(urls)
            
            leads = []
            for i in range(max_len):
                leads.append({
                    "Company Name": company_list[i] if i < len(company_list) else "N/A",
                    "Email Address": email_list[i] if i < len(email_list) else "N/A",
                    "Source/Contact URL": url_list[i] if i < len(url_list) else "N/A"
                })

        df = pd.DataFrame(leads)
        filename = f"Leads_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        if format_type.lower() == "csv":
            return self._create_csv(df, filename)
        elif format_type.lower() == "pdf":
            return self._create_pdf(leads, filename)
        elif format_type.lower() == "txt":
            return self._create_txt(leads, filename)
        else:
            raise ValueError(f"Unsupported format: {format_type}")

    def _create_csv(self, df: pd.DataFrame, filename: str) -> str:
        file_path = os.path.join(self.export_dir, f"{filename}.csv")
        df.to_csv(file_path, index=False)
        return file_path

    def _create_pdf(self, leads_list: list, filename: str) -> str:
        file_path = os.path.join(self.export_dir, f"{filename}.pdf")
        
        # Professional HTML Template with inline CSS
        html_content = f"""
        <html>
        <head>
            <style>
                @page {{
                    size: A4;
                    margin: 20mm;
                    background-color: #ffffff;
                }}
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    color: #333;
                    line-height: 1.6;
                }}
                .header {{
                    border-bottom: 2px solid #2c3e50;
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                h1 {{
                    color: #2c3e50;
                    font-size: 22pt;
                    margin: 0;
                }}
                .meta {{
                    font-size: 10pt;
                    color: #7f8c8d;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                }}
                th {{
                    background-color: #f8f9fa;
                    color: #2c3e50;
                    text-align: left;
                    padding: 12px;
                    border-bottom: 2px solid #dee2e6;
                    font-size: 11pt;
                }}
                td {{
                    padding: 10px;
                    border-bottom: 1px solid #eee;
                    font-size: 10pt;
                    word-break: break-all;
                }}
                tr:nth-child(even) {{ background-color: #fafafa; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>B2B Leads Report</h1>
                <div class="meta">Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Company</th>
                        <th>Email</th>
                        <th>Source URL</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td>{l['Company Name']}</td><td>{l['Email Address']}</td><td>{l['Source/Contact URL']}</td></tr>" for l in leads_list])}
                </tbody>
            </table>
        </body>
        </html>
        """
        HTML(string=html_content).write_pdf(file_path)
        return file_path
    
    def _create_txt(self, leads_list: list, filename: str) -> str:
        file_path = os.path.join(self.export_dir, f"{filename}.txt")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("B2B LEADS REPORT\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("=" * 80 + "\n\n")
            
            for i, lead in enumerate(leads_list, 1):
                f.write(f"LEAD #{i}\n")
                f.write(f"Company: {lead['Company Name']}\n")
                f.write(f"Email: {lead['Email Address']}\n")
                f.write(f"URL: {lead['Source/Contact URL']}\n")
                f.write("-" * 80 + "\n\n")
        
        return file_path
    
    