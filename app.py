from flask import Flask, request, render_template
import pandas as pd
import re
import random
import os
from datetime import datetime

app = Flask(__name__)

# Google Sheet CSV export link
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1271IFIvoL7AwwiSIxJrf3VJ4fLUtjp6LA_r3MXt2HEA/export?format=csv&gid=0"

# Stats log file
STATS_FILE = "link_stats.csv"

# Ensure stats file exists with header
if not os.path.exists(STATS_FILE):
    with open(STATS_FILE, "w") as f:
        f.write("date,campaign,link_type,pid_count,links_generated\n")

def load_data():
    """Load Google Sheet and clean up formatting"""
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = df.columns.str.strip()
    df = df.applymap(lambda val: val.strip().replace('\u00A0', ' ') if isinstance(val, str) else val)
    df.fillna("", inplace=True)
    return df

def log_link_stats(campaign, link_type, pid_count, links_generated):
    """Append or update link generation stats to CSV (date-wise merge)"""
    date_str = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(STATS_FILE):
        stats_df = pd.read_csv(STATS_FILE)
    else:
        stats_df = pd.DataFrame(columns=["date", "campaign", "link_type", "pid_count", "links_generated"])

    mask = (
        (stats_df["date"] == date_str) &
        (stats_df["campaign"] == campaign) &
        (stats_df["link_type"] == link_type) &
        (stats_df["pid_count"] == pid_count)
    )

    if mask.any():
        stats_df.loc[mask, "links_generated"] += links_generated
    else:
        new_row = pd.DataFrame([{
            "date": date_str,
            "campaign": campaign,
            "link_type": link_type,
            "pid_count": pid_count,
            "links_generated": links_generated
        }])
        stats_df = pd.concat([stats_df, new_row], ignore_index=True)

    stats_df.to_csv(STATS_FILE, index=False)

link_types = ["CTA", "VTA", "CTV", "Onelink CTA", "Onelink vta"]

@app.route("/", methods=["GET", "POST"])
def index():
    df = load_data()
    campaigns = df["Campaign"].unique()
    oses = df["os"].unique()

    final_links = []

    if request.method == "POST":
        campaign = request.form['campaign'].strip()
        os_vals = request.form.getlist('os')
        pid_inputs = [pid.strip() for pid in request.form['pid'].split(",") if pid.strip()]
        publisher = request.form['publisher'].strip()
        selected_link_types = request.form.getlist('link_type')

        row_matches = df[(df["Campaign"] == campaign) & (df["os"].isin(os_vals))]

        if row_matches.empty:
            final_links.append("No matching campaign and OS found.")
        else:
            processed_special_types = set()
            kraken_used_combinations = set()
            generated_pid_os_set = set()  # To avoid duplicates

            # Handle special link types for non-Moneyman campaigns
            if campaign.lower() != "moneyman":
                for special_link_type in ["Onelink CTA", "Onelink vta", "CTV"]:
                    if special_link_type in selected_link_types:
                        base_link = ""
                        selected_row = None

                        for _, row in row_matches.iterrows():
                            candidate_link = row.get(special_link_type, "").strip()
                            if candidate_link:
                                base_link = candidate_link
                                selected_row = row
                                break

                        if base_link:
                            pub_key = selected_row.get("Publisher name", "").strip().lstrip("&")

                            for pid in pid_inputs:
                                key = (special_link_type, pid)
                                if key in generated_pid_os_set:
                                    continue

                                link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)

                                if pub_key and f"{pub_key}=" in link:
                                    link = re.sub(rf'{pub_key}=[^&]*', f'{pub_key}={publisher}', link)

                                if campaign.lower() == "banki":
                                    for field in ["c", "af_c_id", "af_channel"]:
                                        link = re.sub(rf'{field}=afl_26_24_cpa_zorka_[^&]*',
                                                      f'{field}=afl_26_24_cpa_zorka_{pid}', link)

                                if campaign.lower().startswith("kraken") and key not in kraken_used_combinations:
                                    af_sub5_random = random.choice(["1491074310", "1617391485", "591560124"])
                                    af_ad_random = random.choice(["Consumer-Banners-Creative-Refresh", "Kraken_Set_Trading"])
                                    link = re.sub(r'af_sub5=[^&]*', f'af_sub5={af_sub5_random}', link)
                                    link = re.sub(r'af_ad=[^&]*', f'af_ad={af_ad_random}', link)
                                    kraken_used_combinations.add(key)

                                final_links.append(f"{special_link_type} (PID: {pid}): {link}")
                                generated_pid_os_set.add(key)

                            log_link_stats(campaign, special_link_type, len(pid_inputs), len(pid_inputs))
                            processed_special_types.add(special_link_type)

                selected_link_types = [lt for lt in selected_link_types if lt not in processed_special_types]

            # Handle normal link types
            for _, row_data in row_matches.iterrows():
                current_os = row_data.get("os", "").strip()
                pub_key = row_data.get("Publisher name", "").strip().lstrip("&")

                for link_type in selected_link_types:
                    base_link = row_data.get(link_type, "").strip()
                    if not base_link:
                        continue

                    link_count_for_type = 0

                    for pid in pid_inputs:
                        key = (link_type, current_os, pid)
                        if key in generated_pid_os_set:
                            continue

                        link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)

                        if pub_key and f"{pub_key}=" in link:
                            link = re.sub(rf'{pub_key}=[^&]*', f'{pub_key}={publisher}', link)

                        if campaign.lower() == "moneyman" and 'af_sub1=' in link:
                            link = re.sub(r'af_sub1=[^&]*', f'af_sub1={pid}', link)

                        if campaign.lower() == "banki":
                            for field in ["c", "af_c_id", "af_channel"]:
                                link = re.sub(rf'{field}=afl_26_24_cpa_zorka_[^&]*',
                                              f'{field}=afl_26_24_cpa_zorka_{pid}', link)

                        if campaign.lower().startswith("kraken"):
                            af_sub5_random = random.choice(["1491074310", "1617391485", "591560124"])
                            af_ad_random = random.choice(["Consumer-Banners-Creative-Refresh", "Kraken_Set_Trading"])
                            link = re.sub(r'af_sub5=[^&]*', f'af_sub5={af_sub5_random}', link)
                            link = re.sub(r'af_ad=[^&]*', f'af_ad={af_ad_random}', link)

                        final_links.append(f"{link_type} (OS: {current_os}, PID: {pid}): {link}")
                        generated_pid_os_set.add(key)
                        link_count_for_type += 1

                    if link_count_for_type > 0:
                        log_link_stats(campaign, link_type, len(pid_inputs), link_count_for_type)

    return render_template("index.html",
                           campaigns=campaigns,
                           oses=oses,
                           link_types=link_types,
                           final_links=final_links)

if __name__ == "__main__":
    app.run(debug=False)