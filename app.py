from flask import Flask, request, render_template, jsonify
import pandas as pd
import random
import os
from datetime import datetime
import re

app = Flask(__name__)

# ================== GOOGLE SHEETS ==================
CAMPAIGN_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1271IFIvoL7AwwiSIxJrf3VJ4fLUtjp6LA_r3MXt2HEA/export?format=csv&gid=0"
PUBLISHER_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1va85AhpQeTR9BxFVNjRONyUuBo-RoFjS3CK04MFHHBk/export?format=csv"
CREATIVE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1UANNPfgWrVwtoQCnMTZUBSn05jD79gj8n4bCJuAWZfs/export?format=csv&gid=0"

STATS_FILE = "link_stats.csv"
LINK_TYPES = ["CTA", "VTA", "CTV", "Onelink CTA", "Onelink vta"]

# ================== INIT STATS ==================
if not os.path.exists(STATS_FILE):
    with open(STATS_FILE, "w") as f:
        f.write("date,campaign,link_type,pid_count,links_generated\n")

# ================== LOADERS ==================
def load_campaign_data():
    df = pd.read_csv(CAMPAIGN_SHEET_CSV)
    df.columns = df.columns.str.strip()
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)
    df.fillna("", inplace=True)
    return df

def load_publishers():
    df = pd.read_csv(PUBLISHER_SHEET_CSV)
    df.columns = df.columns.str.strip()
    df["Pub name"] = df["Pub name"].astype(str).str.strip()
    df["Publisher_ID"] = df["Publisher_ID"].astype(str).str.strip()
    return dict(zip(df["Pub name"], df["Publisher_ID"]))

def load_creatives():
    df = pd.read_csv(CREATIVE_SHEET_CSV)
    df.columns = df.columns.str.strip()
    df["Campaign"] = df["Campaign"].astype(str).str.strip().str.lower()
    df.fillna("", inplace=True)
    return df

# ================== HELPERS ==================
def log_link_stats(campaign, link_type, pid_count, links_generated):
    date_str = datetime.now().strftime("%Y-%m-%d")
    df = pd.read_csv(STATS_FILE) if os.path.exists(STATS_FILE) else pd.DataFrame(
        columns=["date", "campaign", "link_type", "pid_count", "links_generated"]
    )

    mask = (
        (df["date"] == date_str) &
        (df["campaign"] == campaign) &
        (df["link_type"] == link_type) &
        (df["pid_count"] == pid_count)
    )

    if mask.any():
        df.loc[mask, "links_generated"] += links_generated
    else:
        df = pd.concat([df, pd.DataFrame([{
            "date": date_str,
            "campaign": campaign,
            "link_type": link_type,
            "pid_count": pid_count,
            "links_generated": links_generated
        }])], ignore_index=True)

    df.to_csv(STATS_FILE, index=False)

def apply_publisher_macros(link, publisher_id, publisher_macros):
    if not link or not publisher_id or not publisher_macros:
        return link

    macros = [m.strip().lstrip("&") for m in publisher_macros.split(",") if m.strip()]
    for macro in macros:
        if re.search(rf'([?&]){macro}=', link):
            link = re.sub(
                rf'([?&]){macro}=[^&]*',
                rf'\1{macro}={publisher_id}',
                link
            )
        else:
            sep = "&" if "?" in link else "?"
            link = f"{link}{sep}{macro}={publisher_id}"

    return link

def apply_campaign_logic(link, campaign, pid, kraken_used, key):
    cname = campaign.lower().replace(" ", "")

    if cname in ["angelone", "angel_one"]:
        link = re.sub(r'(c=App_Inno_Axponent_)[^&]*', rf'\1{pid}', link)

    if cname == "banki":
        for f in ["c", "af_c_id", "af_channel"]:
            link = re.sub(
                rf'{f}=afl_26_24_cpa_zorka_[^&]*',
                f'{f}=afl_26_24_cpa_zorka_{pid}',
                link
            )

    if cname == "moneyman":
        link = re.sub(r'af_sub1=[^&]*', f'af_sub1={pid}', link)

    if cname.startswith("kraken") and key not in kraken_used:
        link = re.sub(
            r'af_sub5=[^&]*',
            f'af_sub5={random.choice(["1491074310","1617391485","591560124"])}',
            link
        )
        link = re.sub(
            r'af_ad=[^&]*',
            f'af_ad={random.choice(["Consumer-Banners-Creative-Refresh","Kraken_Set_Trading"])}',
            link
        )
        kraken_used.add(key)

    return link

# ================== ROUTES ==================
@app.route("/", methods=["GET", "POST"])
def index():
    df = load_campaign_data()
    publishers_map = load_publishers()
    creative_df = load_creatives()

    creative_columns = [c for c in creative_df.columns if c.lower() != "campaign"]

    campaigns = sorted(df["Campaign"].unique())
    oses = sorted(df["os"].unique())
    final_links = []

    if request.method == "POST":
        campaign = request.form["campaign"].strip()
        campaign_key = campaign.lower()

        os_vals = request.form.getlist("os")
        pid_inputs = [p.strip() for p in request.form["pid"].split(",") if p.strip()]
        selected_link_types = request.form.getlist("link_type")

        # ===== PUBLISHER LOGIC (NEW) =====
        publisher_name = request.form.get("publisher", "").strip()
        manual_publisher_id = request.form.get("manual_publisher_id", "").strip()

        if manual_publisher_id:
            publisher_id = manual_publisher_id
        else:
            publisher_id = publishers_map.get(publisher_name, "")

        rows = df[(df["Campaign"] == campaign) & (df["os"].isin(os_vals))]
        generated = set()
        kraken_used = set()

        # ===== CREATIVE LOOKUP =====
        creative_column = request.form.get("creative_size")
        creative_value = ""

        if creative_column:
            match = creative_df[creative_df["Campaign"] == campaign_key]
            if not match.empty:
                val = str(match.iloc[0].get(creative_column, "")).strip()
                if val and val != "0":
                    creative_value = val

        # ===== SPECIAL LINKS =====
        for lt in ["Onelink CTA", "Onelink vta", "CTV"]:
            if lt not in selected_link_types:
                continue

            base_link = ""
            row_ref = None

            for _, r in rows.iterrows():
                if r.get(lt):
                    base_link = r.get(lt).strip()
                    row_ref = r
                    break

            if not base_link:
                continue

            macros = row_ref.get("Publisher name", "")

            for pid in pid_inputs:
                key = (lt, pid)
                if key in generated:
                    continue

                link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)
                link = apply_publisher_macros(link, publisher_id, macros)
                link = apply_campaign_logic(link, campaign, pid, kraken_used, key)

                if creative_value:
                    if "af_ad=" in link:
                        link = re.sub(r'af_ad=[^&]*', f'af_ad={creative_value}', link)
                    else:
                        link += f"&af_ad={creative_value}"

                final_links.append(f"{lt} (PID: {pid}): {link}")
                generated.add(key)

            log_link_stats(campaign, lt, len(pid_inputs), len(pid_inputs))

        # ===== NORMAL LINKS =====
        for _, row in rows.iterrows():
            os_val = row.get("os", "")
            macros = row.get("Publisher name", "")

            for lt in selected_link_types:
                base_link = row.get(lt, "")
                if not base_link:
                    continue

                for pid in pid_inputs:
                    key = (lt, os_val, pid)
                    if key in generated:
                        continue

                    link = re.sub(r'pid=[^&]*', f'pid={pid}', base_link)
                    link = apply_publisher_macros(link, publisher_id, macros)
                    link = apply_campaign_logic(link, campaign, pid, kraken_used, key)

                    if creative_value:
                        if "af_ad=" in link:
                            link = re.sub(r'af_ad=[^&]*', f'af_ad={creative_value}', link)
                        else:
                            link += f"&af_ad={creative_value}"

                    final_links.append(f"{lt} (OS: {os_val}, PID: {pid}): {link}")
                    generated.add(key)

    return render_template(
        "index.html",
        campaigns=campaigns,
        oses=oses,
        link_types=LINK_TYPES,
        publishers=publishers_map.keys(),
        creative_columns=creative_columns,
        final_links=final_links
    )

# ================== CREATIVE PREVIEW API ==================
@app.route("/get_creative_value")
def get_creative_value():
    campaign = request.args.get("campaign", "").strip().lower()
    creative_column = request.args.get("creative_column", "").strip()

    creative_df = load_creatives()
    value = ""

    if campaign and creative_column:
        match = creative_df[creative_df["Campaign"] == campaign]
        if not match.empty:
            val = str(match.iloc[0].get(creative_column, "")).strip()
            if val and val != "0":
                value = val

    return jsonify({"creative_value": value})

if __name__ == "__main__":
    app.run(debug=True)
