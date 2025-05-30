import os
import shutil
import subprocess
from datetime import datetime
from utils.helpers import logging  # Uses existing logging setup
import glob
import config

# Define project root as the directory that contains this file.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
os.makedirs(DOCS_DIR, exist_ok=True)

TARGET_FILENAME = "index.html"
TARGET_FILEPATH = os.path.join(DOCS_DIR, TARGET_FILENAME)
TARGET_FAILURE_FILENAME = "failure-report.html"
TARGET_FAILURE_FILEPATH = os.path.join(DOCS_DIR, TARGET_FAILURE_FILENAME)

def run_git_command(command_list, cwd=PROJECT_ROOT):
    """Run a git command using subprocess and log the output."""
    try:
        logging.info(f"Running command: {' '.join(command_list)}")
        result = subprocess.run(command_list, cwd=cwd, capture_output=True, text=True, check=True)
        logging.info(result.stdout)
        if result.stderr:
            logging.warning(result.stderr)
        return True
    except Exception as e:
        logging.error(f"Git command failed: {e}")
        return False

def sync_reports_to_docs():
    """
    Copies all daily report HTML files from the reports folder (config.settings['paths']['report_dir'])
    into the docs folder, so that GitHub Pages serves these reports.
    """
    report_dir = config.settings['paths']['report_dir']
    for html_file in glob.glob(os.path.join(report_dir, "*.html")):
        dest_file = os.path.join(DOCS_DIR, os.path.basename(html_file))
        try:
            shutil.copyfile(html_file, dest_file)
            logging.info(f"Synced {html_file} to {dest_file}")
        except Exception as e:
            logging.error(f"Error syncing report {html_file} to docs: {e}")

def publish_both_reports(success_filepath, failure_filepath):
    """
    Publishes the reports by syncing the reports folder into the docs folder
    and updating the landing page. (Removed the copying of individual reports 
    as generic index.html and failure-report.html.)
    """
    # Removed code that copied success_filepath to TARGET_FILEPATH and failure_filepath to TARGET_FAILURE_FILEPATH.
    # Instead, we simply sync and update landing page.
    sync_reports_to_docs()
    update_landing_page()
    
    # After syncing, commit & push updated docs content.
    synced_files = glob.glob(os.path.join(DOCS_DIR, "*.html"))
    files_to_commit = [os.path.relpath(f, PROJECT_ROOT) for f in synced_files]
    commit_message = f"Update GitHub Pages reports: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if run_git_command(["git", "add"] + files_to_commit):
        if run_git_command(["git", "commit", "-m", commit_message]):
            if run_git_command(["git", "push"]):
                logging.info("Reports published successfully via GitHub Pages in a single commit.")
            else:
                logging.error("Git push failed for reports.")
        else:
            logging.error("Git commit failed for reports.")
    else:
        logging.error("Git add failed for reports.")

def update_landing_page():
    """
    Creates/updates index.html as a landing page.
    It scans for both success and failure report files named as success_report_YYYYMMDD.html
    and failure_report_YYYYMMDD.html respectively.
    It displays two sections:
      - Latest 5 Trading Days Success Reports
      - Latest 5 Trading Days Failure Reports
    Each link is built using the trading date parsed from the filename.
    """
    report_dir = config.settings['paths']['report_dir']
    
    # Process Success Reports
    success_files = glob.glob(os.path.join(report_dir, "success_report_????????.html"))
    daily_success = {}
    for filepath in success_files:
        # Filename example: success_report_20250430.html
        basename = os.path.basename(filepath)
        try:
            trading_date = basename.split('_')[2].split('.')[0]  # e.g. "20250430"
            daily_success[trading_date] = filepath  # Later runs overwrite earlier ones.
        except Exception as e:
            logging.warning(f"Could not parse trading date from filename {basename}: {e}")
            continue
    sorted_success = sorted(daily_success.keys(), reverse=True)[:5]
    success_links_html = ""
    for day in sorted_success:
        report_file = os.path.basename(daily_success[day])
        try:
            trading_date_obj = datetime.strptime(day, "%Y%m%d")
            link_text = trading_date_obj.strftime("%d %b %Y")
        except Exception as e:
            link_text = day
        success_links_html += f'<li><a href="{report_file}">{link_text} Success Report</a></li>\n'
    
    # Process Failure Reports
    failure_files = glob.glob(os.path.join(report_dir, "failure_report_????????.html"))
    daily_failure = {}
    for filepath in failure_files:
        # Filename example: failure_report_20250430.html
        basename = os.path.basename(filepath)
        try:
            trading_date = basename.split('_')[2].split('.')[0]
            daily_failure[trading_date] = filepath
        except Exception as e:
            logging.warning(f"Could not parse trading date from filename {basename}: {e}")
            continue
    sorted_failure = sorted(daily_failure.keys(), reverse=True)[:5]
    failure_links_html = ""
    for day in sorted_failure:
        report_file = os.path.basename(daily_failure[day])
        try:
            trading_date_obj = datetime.strptime(day, "%Y%m%d")
            link_text = trading_date_obj.strftime("%d %b %Y")
        except Exception as e:
            link_text = day
        failure_links_html += f'<li><a href="{report_file}">{link_text} Failure Report</a></li>\n'
    
    landing_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ZT-3 Stock Screener Reports</title>
  <style>
      body {{ font-family: 'Segoe UI', sans-serif; background-color: #f8f9fa; color: #212529; padding: 20px; }}
      .container {{ max-width: 900px; margin: auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
      h1, h2 {{ text-align: center; }}
      ul {{ list-style: none; padding: 0; }}
      li {{ margin: 10px 0; }}
      a {{ color: #007bff; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .section {{ margin-top: 30px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>ZT-3 Stock Screener Reports</h1>
    <div class="section">
      <h2>Latest 5 Trading Days Success Reports</h2>
      <ul>
        {success_links_html if success_links_html else "<li>No Success Reports Available</li>"}
      </ul>
    </div>
    <div class="section">
      <h2>Latest 5 Trading Days Failure Reports</h2>
      <ul>
        {failure_links_html if failure_links_html else "<li>No Failure Reports Available</li>"}
      </ul>
    </div>
  </div>
</body>
</html>"""
    # Replace destination so that the landing page is created in docs folder, not the reports folder:
    index_filepath = os.path.join(DOCS_DIR, "index.html")
    with open(index_filepath, "w", encoding="utf-8") as f:
        f.write(landing_html)
    logging.info(f"Landing page updated at: {index_filepath}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        logging.error("Usage: python report_host.py path/to/success_report.html [path/to/failure_report.html]")
    else:
        success_report = sys.argv[1]
        failure_report = sys.argv[2] if len(sys.argv) >= 3 else None
        publish_both_reports(success_report, failure_report)
