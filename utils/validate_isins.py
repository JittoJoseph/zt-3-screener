#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Validate Instrument Keys from stock_list.csv using Upstox API.

This script reads the stock list, constructs the Upstox instrument key
(assuming NSE Equity), and attempts to fetch minimal historical data
to verify if the key is valid on the Upstox platform.
"""

import sys
import os
# Add project root to path to allow importing config, data_fetcher etc.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import requests # Ensure requests is imported
from datetime import datetime, timedelta, timezone # Import timezone
import time
import json # Import json for discord payload
import pytz # Import pytz for IST conversion
import csv # Import csv module
from concurrent.futures import ThreadPoolExecutor, as_completed  # NEW import
import signal  # Add signal module for better interrupt handling

# Import necessary functions from our modules
import config
from data_fetcher import get_api_headers, API_VERSION # Import necessary items
from utils.helpers import load_stock_list, logging # Import from helpers

# --- Configuration ---
# Assume NSE Equity for constructing the key. Modify if needed.
EXCHANGE = "NSE"
INSTRUMENT_TYPE = "EQ"
VALIDATION_INTERVAL = "1minute" # Use a small interval for quick check
VALIDATION_DAYS_BACK = 2 # Check data for the last couple of days

# --- Helper Functions ---

def validate_instrument_key(instrument_key, headers):
    """
    Attempts to fetch minimal historical data to validate an instrument key.

    Args:
        instrument_key (str): The Upstox instrument key (e.g., 'NSE_EQ|INE002A01018').
        headers (dict): The authentication headers for the API request.

    Returns:
        bool: True if the key seems valid (API returns success), False otherwise.
    """
    # Use a very small date range for validation
    to_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d') # Yesterday
    from_date = (datetime.now() - timedelta(days=VALIDATION_DAYS_BACK)).strftime('%Y-%m-%d')

    # URL Encode the instrument key for safety
    encoded_instrument_key = requests.utils.quote(instrument_key)

    # Construct URL based on historical data endpoint structure
    url = f"https://api.upstox.com/{API_VERSION}/historical-candle/{encoded_instrument_key}/{VALIDATION_INTERVAL}/{to_date}/{from_date}"
    logging.debug(f"Validation URL: {url}")

    for attempt in range(2):  # Try twice
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    logging.debug(f"Validation success for {instrument_key} (Status: {data.get('status')})")
                    return True
                else:
                    logging.warning(f"Validation failed for {instrument_key}. API Status: {data.get('status')}, Message: {data.get('message', 'N/A')}")
                    if attempt == 0:  # Only retry on first attempt
                        logging.info(f"Retrying {instrument_key} after 3 seconds...")
                        time.sleep(3)  # Increased from 1 to 3 seconds
                        continue
                    return False
                    
            elif response.status_code == 429:  # Rate limit hit
                logging.warning(f"Rate limit hit for {instrument_key}. HTTP Status: 429.")
                if attempt == 0:  # Only retry on first attempt
                    logging.info(f"Retrying {instrument_key} after 3 seconds...")
                    time.sleep(3)  # Increased from 1 to 3 seconds
                    continue
                return False
                
            elif response.status_code == 404:
                logging.warning(f"Validation failed for {instrument_key}. HTTP Status: 404 (Not Found)")
                return False  # Don't retry on 404
                
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('errors', [{}])[0].get('message', response.text[:100])
                    logging.warning(f"Validation failed for {instrument_key}. HTTP Status: 400 (Bad Request). Reason: {error_msg}")
                except json.JSONDecodeError:
                    logging.warning(f"Validation failed for {instrument_key}. HTTP Status: 400 (Bad Request). Response: {response.text[:200]}")
                return False  # Don't retry on 400
                
            else:
                logging.error(f"Validation HTTP error for {instrument_key}. Status: {response.status_code}, Response: {response.text[:200]}")
                if attempt == 0:  # Only retry on first attempt
                    logging.info(f"Retrying {instrument_key} after 3 seconds...")
                    time.sleep(3)  # Increased from 1 to 3 seconds
                    continue
                return False

        except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            logging.error(f"Validation request error for {instrument_key} on attempt {attempt+1}: {e}")
            if attempt == 0:  # Only retry on first attempt
                logging.info(f"Retrying {instrument_key} after 3 seconds...")
                time.sleep(3)  # Increased from 1 to 3 seconds
                continue
            return False
            
        except Exception as e:
            logging.error(f"Unexpected error during validation for {instrument_key} on attempt {attempt+1}: {e}")
            if attempt == 0:  # Only retry on first attempt
                logging.info(f"Retrying {instrument_key} after 3 seconds...")
                time.sleep(3)  # Increased from 1 to 3 seconds
                continue
            return False
            
    return False  # If we get here, all attempts failed

def send_stocklist_to_discord(valid_stocks, invalid_stocks, total_checked, duration_seconds, webhook_url):
    """Sends a summary of validation results (valid count, invalid list) to Discord."""
    if not webhook_url:
        logging.warning("Discord stocklist webhook URL not configured. Skipping notification.")
        return

    # --- Common Info ---
    # Format duration
    duration_str = f"{duration_seconds:.2f} seconds"
    if duration_seconds > 60:
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        duration_str = f"{minutes}m {seconds}s"

    # Get current time in IST and format conditionally
    try:
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist_tz)
        today_ist_date = now_ist.date()
        if now_ist.date() == today_ist_date:
            now_formatted_str = now_ist.strftime('Today at %I:%M %p')
        else:
            now_formatted_str = now_ist.strftime('%d %b %Y, %I:%M %p')
    except Exception as e:
        logging.error(f"Error getting/formatting IST time: {e}")
        now_formatted_str = datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')

    username = "Stocklist Validator"
    embeds_to_send = [] # Will hold the summary embed and potentially invalid list parts

    # --- Footer Text ---
    footer_text_common = f"Took {duration_str}\n{now_formatted_str}"

    # --- Embed Generation ---
    MAX_CHARS_PER_DESC = 3800 # Keep for invalid list description if needed
    MAX_LINES_PER_DESC = 45   # Keep for invalid list description if needed

    # Determine overall status color
    if not valid_stocks and not invalid_stocks:
        # Should not happen if total_checked > 0, but handle anyway
        color = 0x808080 # Grey
        summary_desc = f"Checked {total_checked} stocks. No valid or invalid stocks found (unexpected)."
    elif invalid_stocks:
        color = 0xFF0000 # Red if any invalid
        summary_desc = f"Checked {total_checked} stocks. Found issues."
    else:
        color = 0x00FF00 # Green if all valid
        summary_desc = f"Checked {total_checked} stocks. All entries are valid."

    # Create the main summary embed
    summary_embed = {
        "title": "Stock List Validation Summary",
        "description": summary_desc,
        "color": color,
        "fields": [
            {"name": "Valid Stocks", "value": str(len(valid_stocks)), "inline": True},
            {"name": "Invalid/Error Stocks", "value": str(len(invalid_stocks)), "inline": True},
        ],
        "footer": {"text": footer_text_common},
    }
    embeds_to_send.append(summary_embed)

    # Add Invalid Stocks List (if any, potentially split)
    if invalid_stocks:
        logging.info(f"Generating embed(s) for {len(invalid_stocks)} invalid stocks list...")
        color_invalid = 0xFF0000 # Red
        current_desc_invalid = ""
        part_num_invalid = 1
        lines_needed_invalid = len(invalid_stocks)
        total_parts_invalid = (lines_needed_invalid + MAX_LINES_PER_DESC - 1) // MAX_LINES_PER_DESC
        # Footer only needed if this is the *only* embed (i.e., no valid stocks found previously)
        # However, the summary embed is always added first now, so invalid list never needs the main footer.
        footer_invalid = None

        for i, stock in enumerate(invalid_stocks):
            line = f"{i+1}. {stock['symbol']} ({stock['isin']})\n"
            if (len(current_desc_invalid) + len(line) > MAX_CHARS_PER_DESC and current_desc_invalid) or \
               current_desc_invalid.count('\n') >= MAX_LINES_PER_DESC:
                embed = {
                    "title": f"Invalid Stock List ({len(invalid_stocks)} Total)" + (f" - Part {part_num_invalid}/{total_parts_invalid}" if total_parts_invalid > 1 else ""),
                    "description": current_desc_invalid,
                    "color": color_invalid,
                    # No footer needed for these parts as summary embed has it
                }
                embeds_to_send.append(embed)
                current_desc_invalid = line
                part_num_invalid += 1
            else:
                current_desc_invalid += line

        # Add the last chunk for invalid stocks
        if current_desc_invalid:
             embed = {
                "title": f"Invalid Stock List ({len(invalid_stocks)} Total)" + (f" - Part {part_num_invalid}/{total_parts_invalid}" if total_parts_invalid > 1 else ""),
                "description": current_desc_invalid,
                "color": color_invalid,
             }
             # No footer needed here either
             embeds_to_send.append(embed)

    # --- Send the embed message(s) ---
    if not embeds_to_send:
        logging.warning("No embeds generated to send.")
        return

    logging.info(f"Sending {len(embeds_to_send)} embed(s) to Discord...")
    max_embeds_per_message = 10
    num_messages = (len(embeds_to_send) + max_embeds_per_message - 1) // max_embeds_per_message
    for i in range(num_messages):
        start_index = i * max_embeds_per_message
        end_index = start_index + max_embeds_per_message
        embed_chunk = embeds_to_send[start_index:end_index]
        if not embed_chunk: continue
        payload = {"username": username, "embeds": embed_chunk}
        try:
            response = requests.post(webhook_url, json=payload, timeout=15)
            response.raise_for_status()
            logging.info(f"Discord embed notification sent successfully (Message {i+1}/{num_messages}).")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending Discord embed notification (Message {i+1}/{num_messages}): {e}")
            if e.response is not None: logging.error(f"Discord Response: {e.response.text}")
        except Exception as e:
             logging.error(f"Unexpected error sending Discord embed notification (Message {i+1}/{num_messages}): {e}")
        if num_messages > 1 and i < num_messages - 1: time.sleep(1)

# --- Main Validation Logic ---

def run_validation():
    """Loads stocks, validates keys, sends results, and saves valid list."""
    start_time = time.time() # Record start time
    logging.info("Starting ISIN validation process...")

    # 1. Get API Headers (includes getting/checking token)
    headers = get_api_headers()
    if not headers:
        logging.error("Cannot run validation. Failed to get API headers (check token).")
        # Instructions on how to get token are printed by get_access_token()
        return

    # 2. Load Stock List (Load from the original list for validation)
    original_stock_list_file = config.settings['paths']['stock_list_file']
    stocks = load_stock_list(original_stock_list_file) # Pass the specific file
    if not stocks:
        logging.error(f"Cannot run validation. Failed to load stock list '{original_stock_list_file}' or list is empty.")
        return

    logging.info(f"Found {len(stocks)} stocks to validate.")
    results = {'valid': [], 'invalid': []}

    # New helper for threaded processing
    def process_stock(index, stock):
        symbol = stock['symbol']
        isin = stock['isin']
        instrument_key = f"{EXCHANGE}_{INSTRUMENT_TYPE}|{isin}"
        is_valid = validate_instrument_key(instrument_key, headers)
        # No additional delay here - validate_instrument_key already has retry logic with delays
        return index, stock, is_valid

    # Set up signal handler for better interrupt handling
    interrupted = False
    def signal_handler(sig, frame):
        nonlocal interrupted
        if not interrupted:
            logging.warning("Interrupt signal received. Shutting down gracefully...")
            interrupted = True
        else:
            logging.warning("Second interrupt received. Forcing exit...")
            sys.exit(1)
    
    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal_handler)

    # Use ThreadPoolExecutor for parallel validation with more workers
    valid_count = 0
    invalid_count = 0
    validation_loop_start_time = time.time()
    
    # Enable catching KeyboardInterrupt during thread execution
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:  # Increased workers
            # Submit all jobs at once
            futures_to_stock = {
                executor.submit(process_stock, i, stock): (i, stock) 
                for i, stock in enumerate(stocks)
            }
            
            # Process completed futures as they finish
            for future in as_completed(futures_to_stock):
                if interrupted:
                    logging.warning("Processing interrupted. Skipping remaining stocks.")
                    break
                
                try:
                    index, stock, is_valid = future.result()
                    symbol = stock['symbol']
                    isin = stock['isin']
                    
                    if is_valid:
                        logging.info(f"{index+1}. [VALID] {symbol} ({isin})")
                        valid_count += 1
                        results['valid'].append({
                            'symbol': symbol, 
                            'isin': isin, 
                            'instrument_key': f"{EXCHANGE}_{INSTRUMENT_TYPE}|{isin}"
                        })
                    else:
                        logging.warning(f"{index+1}. [INVALID] {symbol} ({isin})")
                        invalid_count += 1
                        results['invalid'].append({
                            'symbol': symbol, 
                            'isin': isin, 
                            'instrument_key': f"{EXCHANGE}_{INSTRUMENT_TYPE}|{isin}"
                        })
                except Exception as e:
                    # Get the original stock info from the futures mapping
                    i, stock = futures_to_stock[future]
                    logging.error(f"Error processing stock {stock['symbol']}: {e}")
                    invalid_count += 1
                    results['invalid'].append({
                        'symbol': stock['symbol'], 
                        'isin': stock['isin'], 
                        'instrument_key': f"{EXCHANGE}_{INSTRUMENT_TYPE}|{stock['isin']}",
                        'error': str(e)
                    })
    
    except KeyboardInterrupt:
        interrupted = True
        logging.warning("Keyboard interrupt received. Shutting down gracefully...")
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
        
    if interrupted:
        logging.warning("Validation was interrupted before completion.")
        logging.warning(f"Processed {valid_count + invalid_count} of {len(stocks)} stocks before interruption.")
        
    validation_loop_end_time = time.time()
    total_duration_seconds = validation_loop_end_time - validation_loop_start_time

    logging.info("-" * 50)
    logging.info("Validation Summary:")
    logging.info(f"Total Stocks Checked: {len(stocks)}")
    logging.info(f"Valid Instrument Keys: {valid_count}")
    logging.info(f"Invalid/Error Keys: {invalid_count}")
    logging.info(f"Validation Duration: {total_duration_seconds:.2f} seconds")
    logging.info("-" * 50)
    if results['invalid']:
        logging.warning("Invalid ISINs/Symbols found:")
        for item in results['invalid']:
            logging.warning(f"  - {item['symbol']} ({item['isin']})")
        logging.warning("Please check these entries in your stock_list.csv")

    # 5. Save Valid List to File
    valid_stock_list_file = config.settings['paths']['valid_stock_list_file']
    if results['valid']:
        try:
            with open(valid_stock_list_file, mode='w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['symbol', 'isin']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                # Write only symbol and isin from the valid results
                writer.writerows([{'symbol': s['symbol'], 'isin': s['isin']} for s in results['valid']])
            logging.info(f"Saved {len(results['valid'])} valid stocks to '{valid_stock_list_file}'.")
        except IOError as e:
            logging.error(f"Failed to save valid stock list to '{valid_stock_list_file}': {e}")
        except Exception as e:
            logging.error(f"Unexpected error saving valid stock list: {e}")
    else:
        logging.warning(f"No valid stocks found. '{valid_stock_list_file}' will not be created/updated.")
        # Optionally delete the file if it exists and no valid stocks are found
        if os.path.exists(valid_stock_list_file):
            try:
                os.remove(valid_stock_list_file)
                logging.info(f"Removed existing '{valid_stock_list_file}' as no valid stocks were found.")
            except OSError as e:
                logging.warning(f"Could not remove existing '{valid_stock_list_file}': {e}")


    # 6. Send Validation Results to Discord
    stocklist_webhook_url = config.get_discord_stocklist_webhook_url()
    send_stocklist_to_discord(
        results['valid'],
        results['invalid'],
        len(stocks),
        total_duration_seconds,
        stocklist_webhook_url
    )

    # Optionally save results to a file
    # output_file = os.path.join(config.settings['paths']['output_dir'], 'isin_validation_results.json')
    # try:
    #     with open(output_file, 'w') as f:
    #         json.dump(results, f, indent=2)
    #     logging.info(f"Validation results saved to {output_file}")
    # except Exception as e:
    #     logging.error(f"Failed to save validation results: {e}")


if __name__ == "__main__":
    # Ensure logging is set up via helpers
    try:
        # This ensures the logging config in helpers runs
        import utils.helpers
    except ImportError as e:
         print(f"Error importing utils.helpers: {e}. Ensure script is run from project root or PYTHONPATH is set.")
         sys.exit(1)

    try:
        run_validation()
    except KeyboardInterrupt:
        print("\nScript interrupted by user. Exiting.")
        sys.exit(1)
