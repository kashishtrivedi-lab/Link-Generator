from flask import Flask, request, render_template
import pandas as pd
import random
import os
from datetime import datetime
import re

app = Flask(__name__)

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1271IFIvoL7AwwiSIxJrf3VJ4fLUtjp6LA_r3MXt2HEA/export?format=csv&gid=0"
STATS_FILE = "link_stats.csv"

if not os.path.exists(STATS_FILE):
    with open(STATS_FILE, "w") as f:
        f.write("date,campaign,link_type,pid_count,links_generated\n")


def load_data():
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df.columns = df.columns.str.strip()
    df = df.applymap(lambda v: v.strip().replace('\u00A0', ' ') if isinstance(v, str) else v)
    df.fillna("", inplace=True)
    return df


def log_link_stats(campaign, link_type, pid_count, links_generated):
    date_str = datetime.now().strftime("%Y-%m-%d")
    stats_df = pd.read_csv(STATS_FILE) if os.path.exists(STATS_FILE) else pd.DataFrame(
        columns=["date", "campaign", "link_type", "pid_count", "links_generated"]
    )

    mask = (
        (stats_df["date"] == date_str) &
        (stats_df["campaign"] == campaign) &
        (stats_df["link_type"] == link_type) &
        (stats_df["pid_count"] == pid_count)
    )

    if mask.any():
        stats_df.loc[mask, "links_generated"] += links_generated
    else:
        stats_df = pd.concat([stats_df, pd.DataFrame([{
            "date": date_str,
            "campaign": campaign,
            "link_type": link_type,
            "pid_count": pid_count,
            "links_generated": links_generated
        }])], ignore_index=True)

    stats_df.to_csv(STATS_FILE, index=False)


def apply_publisher_macros(link, publisher, publisher_macros):
    if not link or not publisher or not publisher_macros:
        return link

    macros = [m.strip().lstrip("&") for m in publisher_macros.split(",") if m.strip()]
    for macro in macros:
        if re.search(rf'([?&]){macro}=', link):
            link = re.sub(rf'([?&]){macro}=[^&]*', rf'\1{macro}={publisher}', link)
        else:
            sep = "&" if "?" in link else "?"
            link = f"{link}{sep}{macro}={publisher}"
    return link


link_types = ["CTA", "VTA", "CTV", "Onelink CTA", "Onelink vta"]

@app.route("/", methods=["GET", "POST"])
def index():
    df = load_data()
    campaigns = df["Campaign"].unique()
    oses = df["os"].unique()
    final_links = []

    if request.method == "POST":
        campaign = request.form["campaign"].strip()
        os_vals = request.form.getlist("os")
        pid_inputs = [p.strip() for p in request.form["pid"].split(",") if p.strip()]
        publisher = request.form["publisher"].strip()
        selected_link_types = request.form.getlist("link_type")

        row_matches = df[(df["Campaign"] == campaign) & (df["os"].isin(os_vals))]
        if row_matches.empty:
            final_links.append("No matching campaign and OS found.")
            return render_template("index.html", campaigns=campaigns, oses=oses,
                                   link_types=link_types, final_links=final_links)

        generated_set = set()
        kraken_used = set()

        # ---------- SPECIAL LINKS ----------
        for lt in ["Onelink CTA", "Onelink vta", "CTV"]:
            if lt not in selected_link_types:
                continue
            base_link, row_ref = "", None
            for _, r in row_matches.iterrows():
                if r.get(lt):
                    base_link, row_ref = r.get(lt).strip(), r
                    break
            if not base_link:
                continue
            publisher_macros = row_ref.get("Publisher name", "").strip()
            for pid in pid_inputs:
                key = (lt, pid)
                if key in generated_set:
                    continue
                link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)
                link = apply_publisher_macros(link, publisher, publisher_macros)

                # ✅ Angel One logic: replace anything after "c=App_Inno_Axponent_" with the actual PID
                if campaign.lower().replace(" ", "") in ["angelone", "angel_one"]:
                    link = re.sub(r'(c=App_Inno_Axponent_)[^&]*', rf'\1{pid}', link)

                # Kraken logic
                if campaign.lower().startswith("kraken") and key not in kraken_used:
                    link = re.sub(r'af_sub5=[^&]*',
                                  f'af_sub5={random.choice(["1491074310","1617391485","591560124"])}', link)
                    link = re.sub(r'af_ad=[^&]*',
                                  f'af_ad={random.choice(["Consumer-Banners-Creative-Refresh","Kraken_Set_Trading"])}',
                                  link)
                    kraken_used.add(key)

                final_links.append(f"{lt} (PID: {pid}): {link}")
                generated_set.add(key)
            log_link_stats(campaign, lt, len(pid_inputs), len(pid_inputs))

        # ---------- NORMAL LINKS ----------
        for _, row in row_matches.iterrows():
            os_val = row.get("os", "").strip()
            publisher_macros = row.get("Publisher name", "").strip()
            for lt in selected_link_types:
                base_link = row.get(lt, "").strip()
                if not base_link:
                    continue
                for pid in pid_inputs:
                    key = (lt, os_val, pid)
                    if key in generated_set:
                        continue
                    link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)
                    link = apply_publisher_macros(link, publisher, publisher_macros)

                    # ✅ Angel One logic for normal links
                    if campaign.lower().replace(" ", "") in ["angelone", "angel_one"]:
                        link = re.sub(r'(c=App_Inno_Axponent_)[^&]*', rf'\1{pid}', link)

                    final_links.append(f"{lt} (OS: {os_val}, PID: {pid}): {link}")
                    generated_set.add(key)

    return render_template("index.html", campaigns=campaigns,
                           oses=oses, link_types=link_types,
                           final_links=final_links)

if __name__ == "__main__":
    app.run(debug=False)
