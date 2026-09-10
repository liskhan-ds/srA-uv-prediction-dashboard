import sqlite3
import requests
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from espn_stats_fetcher import get_espn_player_stats
import json
import pandas as pd
import numpy as np

DB_PATH = os.path.join(BASE_DIR, "sra_data.db")

TEAM_NAME_MAP = {
    "Internazionale": "인테르", "Inter Milan": "인테르", "Inter": "인테르",
    "AC Milan": "AC 밀란", "Milan": "AC 밀란",
    "Juventus": "유벤투스",
    "Napoli": "나폴리",
    "Atalanta": "아탈란타",
    "AS Roma": "AS 로마", "Roma": "AS 로마",
    "Lazio": "라치오",
    "Fiorentina": "피오렌티나",
    "Bologna": "볼로냐",
    "Torino": "토리노",
    "Genoa": "제노아",
    "Udinese": "우디네세",
    "Cagliari": "칼리아리",
    "Parma": "파르마",
    "Monza": "몬차",
    "Como": "코모",
    "Lecce": "레체",
    "Venezia": "베네치아",
    "Sassuolo": "사수올로",
    "Frosinone": "프로시노네"
}

RAW_TO_STD_TEAM = {
    "Internazionale": "Internazionale", "Inter Milan": "Internazionale", "Inter": "Internazionale",
    "AC Milan": "AC Milan", "Milan": "AC Milan",
    "Juventus": "Juventus",
    "Napoli": "Napoli",
    "Atalanta": "Atalanta",
    "AS Roma": "AS Roma", "Roma": "AS Roma",
    "Lazio": "Lazio",
    "Fiorentina": "Fiorentina",
    "Bologna": "Bologna",
    "Torino": "Torino",
    "Genoa": "Genoa",
    "Udinese": "Udinese",
    "Cagliari": "Cagliari",
    "Parma": "Parma",
    "Monza": "Monza",
    "Como": "Como",
    "Lecce": "Lecce",
    "Venezia": "Venezia",
    "Sassuolo": "Sassuolo",
    "Frosinone": "Frosinone"
}

def normalize_team_name(raw_name):
    for key, val in TEAM_NAME_MAP.items():
        if key.lower() in raw_name.lower() or raw_name.lower() in key.lower():
            return val
    return raw_name

def get_std_team_name(raw_name):
    for key, val in RAW_TO_STD_TEAM.items():
        if key.lower() in raw_name.lower() or raw_name.lower() in key.lower():
            return val
    return raw_name

MATCHWEEK_1_ABSENCES = {}

def get_team_roster(team_name, absentees=None):
    roster_file = os.path.join(BASE_DIR, "rosters_2026.json")
    if not os.path.exists(roster_file):
        return {"starters": [], "subs": []}
    with open(roster_file, "r", encoding="utf-8") as f:
        rosters = json.load(f)
        
    std_tname = get_std_team_name(team_name)
    plist = rosters.get(std_tname, [])
    if not plist:
        # Try matching by name
        for k, v in rosters.items():
            if k.lower() in team_name.lower() or team_name.lower() in k.lower():
                plist = v
                break
                
    if absentees is None:
        absentees = []
        
    available = [p for p in plist if p.get("name") not in absentees]
    
    for p in available:
        p["calc_uv"] = calculate_player_uv(p, std_tname)
        
    gks = sorted([p for p in available if p.get("pos") in ["G", "GK"]], key=lambda x: x["calc_uv"], reverse=True)
    dfs = sorted([p for p in available if p.get("pos") in ["D", "DF"]], key=lambda x: x["calc_uv"], reverse=True)
    mfs = sorted([p for p in available if p.get("pos") in ["M", "MF"]], key=lambda x: x["calc_uv"], reverse=True)
    fws = sorted([p for p in available if p.get("pos") in ["F", "FW"]], key=lambda x: x["calc_uv"], reverse=True)
    
    starters = gks[:1] + dfs[:4] + mfs[:3] + fws[:3]
    subs = (gks[1:2] + dfs[4:6] + mfs[3:5] + fws[3:5])[:5]
    return {"starters": starters, "subs": subs}

def calculate_player_uv(player_data, team_name=""):
    p_name_raw = player_data.get("name", "")
    
    rating = None
    goals_per90 = 0.0
    position = player_data.get("pos", "MF")
    
    espn_res = get_espn_player_stats(p_name_raw)
    if espn_res:
        rating, goals_per90 = espn_res
        
    pos_clean = "GK" if position in ["G", "GK"] else ("DF" if position in ["D", "DF"] else ("MF" if position in ["M", "MF"] else "FW"))
    
    if rating is None or rating == 0:
        if pos_clean == "GK":
            raw_uv = 0.95
        elif pos_clean == "DF":
            raw_uv = 0.90
        elif pos_clean == "MF":
            raw_uv = 0.88
        else:
            raw_uv = 0.85
    elif rating >= 6.88:
        if pos_clean in ["GK", "DF", "MF"]:
            raw_uv = 1.0 + (rating - 6.88) * 0.50
        else: # FW
            raw_uv = 1.0 + (rating - 6.88) * 0.50 + (goals_per90 * 0.40)
    else:
        slope = 0.80 if pos_clean == "MF" else 0.65
        raw_uv = 1.0 + (rating - 6.88) * slope + (goals_per90 * 0.40 if pos_clean == "FW" else 0.0)
        
    return round(min(max(raw_uv, 0.1), 2.5), 3)

def calculate_wuv(team_name, absentees=None):
    roster = get_team_roster(team_name, absentees=absentees)
    starters = roster.get("starters", [])
    subs = roster.get("subs", [])
    
    st_uvs = [calculate_player_uv(p, team_name) for p in starters]
    sub_uvs = [calculate_player_uv(p, team_name) for p in subs]
    
    st_avg = sum(st_uvs) / len(st_uvs) if st_uvs else 0.95
    sub_avg = sum(sub_uvs) / len(sub_uvs) if sub_uvs else 0.85
    
    st_tot_sum = sum(st_uvs)
    sub_tot_sum = sum(sub_uvs)
    raw_wuv = 0.85 * st_avg + 0.15 * sub_avg
    team_wuv = round(raw_wuv * 11.0, 3)
    
    pos_sums = {"GK": 0.0, "DF": 0.0, "MF": 0.0, "FW": 0.0}
    starters_detail = []
    for p in starters:
        uv = calculate_player_uv(p, team_name)
        pos = p.get("pos", "M")
        pos_clean = "GK" if pos in ["G","GK"] else ("DF" if pos in ["D","DF"] else ("MF" if pos in ["M","MF"] else "FW"))
        pos_sums[pos_clean] += uv
        starters_detail.append({"name": p.get("name"), "pos": pos_clean, "uv": uv})
        
    tot_st_uv = sum(pos_sums.values()) or 1.0
    gk_wuv = round(team_wuv * (pos_sums["GK"] / tot_st_uv), 2)
    df_wuv = round(team_wuv * (pos_sums["DF"] / tot_st_uv), 2)
    mf_wuv = round(team_wuv * (pos_sums["MF"] / tot_st_uv), 2)
    fw_wuv = round(team_wuv * (pos_sums["FW"] / tot_st_uv), 2)
    
    return {
        "team_wuv": team_wuv,
        "st_avg": round(st_avg, 3),
        "sub_avg": round(sub_avg, 3),
        "st_sum": round(st_tot_sum, 3),
        "sub_sum": round(sub_tot_sum, 3),
        "gk_wuv": gk_wuv,
        "df_wuv": df_wuv,
        "mf_wuv": mf_wuv,
        "fw_wuv": fw_wuv,
        "starters_detail": starters_detail
    }

def get_match_prediction(home_team, away_team):
    h_info = calculate_wuv(home_team)
    a_info = calculate_wuv(away_team)
    
    h_total = h_info["team_wuv"] + 0.15
    a_total = a_info["team_wuv"]
    
    gap = h_total - a_total
    
    home_kr = TEAM_NAME_MAP.get(home_team, home_team)
    away_kr = TEAM_NAME_MAP.get(away_team, away_team)
    
    if abs(gap) <= 0.40:
        winner = "무승부"
        code = "DRAW"
    elif gap > 0.40:
        winner = f"{home_kr} 승"
        code = "HOME"
    else:
        winner = f"{away_kr} 승"
        code = "AWAY"
        
    z = gap
    lh = 1.55 * z
    la = -1.55 * z
    ld = 0.35 - 1.25 * abs(z)
    
    eh, ed, ea = np.exp(lh), np.exp(ld), np.exp(la)
    tot = eh + ed + ea
    
    p_home = round((eh / tot) * 100, 1)
    p_draw = round((ed / tot) * 100, 1)
    p_away = round((ea / tot) * 100, 1)
    
    sc_h = int(round(1.35 * (h_total / 11.0)))
    sc_a = int(round(1.35 * (a_total / 11.0)))
    
    if code == "DRAW":
        sc_h = sc_a = int(round((sc_h + sc_a) / 2.0))
    elif code == "HOME" and sc_h <= sc_a:
        sc_h = sc_a + 1
    elif code == "AWAY" and sc_a <= sc_h:
        sc_a = sc_h + 1
        
    return {
        "home_wuv": h_info,
        "away_wuv": a_info,
        "h_total": h_total,
        "a_total": a_total,
        "gap": gap,
        "winner": winner,
        "code": code,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "sc_h": sc_h,
        "sc_a": sc_a
    }

def run_pipeline(mode="all"):
    url_mw1 = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard?dates=20260820-20260825"
    url_mw2 = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard?dates=20260826-20260901"
    url_mw3 = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard?dates=20260902-20260908"
    
    try:
        resp_mw1 = requests.get(url_mw1, timeout=10).json()
        resp_mw2 = requests.get(url_mw2, timeout=10).json()
        resp_mw3 = requests.get(url_mw3, timeout=10).json()
    except Exception as e:
        print(f"Error fetching ESPN API: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT UNIQUE,
        round_name TEXT NOT NULL,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        match_date TEXT NOT NULL,
        home_wuv REAL NOT NULL,
        away_wuv REAL NOT NULL,
        home_total_wuv REAL NOT NULL,
        away_total_wuv REAL NOT NULL,
        gap REAL NOT NULL,
        predicted_winner TEXT NOT NULL,
        prob_home REAL NOT NULL,
        prob_draw REAL NOT NULL,
        prob_away REAL NOT NULL,
        score_home INTEGER NOT NULL,
        score_away INTEGER NOT NULL,
        actual_score_home INTEGER,
        actual_score_away INTEGER,
        actual_winner TEXT,
        is_correct INTEGER
    )
    """)

    def process_espn_events(events, round_label, mw_prefix):
        for idx, e in enumerate(events, 1):
            comp = e.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
                
            home_comp = competitors[0] if competitors[0].get("homeAway") == "home" else competitors[1]
            away_comp = competitors[1] if competitors[0].get("homeAway") == "home" else competitors[0]
            
            h_team_raw = home_comp.get("team", {}).get("displayName", "")
            a_team_raw = away_comp.get("team", {}).get("displayName", "")
            
            h_team = normalize_team_name(h_team_raw)
            a_team = normalize_team_name(a_team_raw)
            
            h_team_std = get_std_team_name(h_team_raw)
            a_team_std = get_std_team_name(a_team_raw)
            
            date_raw = e.get("date", "")
            
            status_type = e.get("status", {}).get("type", {}).get("name", "")
            is_completed = (status_type == "STATUS_FULL_TIME")
            is_cancelled = status_type in ["STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED", "STATUS_ABANDONED"]
            
            act_sc_h = int(home_comp.get("score")) if (is_completed and home_comp.get("score") is not None) else None
            act_sc_a = int(away_comp.get("score")) if (is_completed and away_comp.get("score") is not None) else None
            
            if is_completed and act_sc_h is not None and act_sc_a is not None:
                if act_sc_h > act_sc_a:
                    act_winner = f"{h_team} 승"
                elif act_sc_a > act_sc_h:
                    act_winner = f"{a_team} 승"
                else:
                    act_winner = "무승부"
            elif is_cancelled:
                act_winner = "경기 연기"
            else:
                act_winner = None
                
            mid = f"2026_{mw_prefix}_{idx}"
            
            cursor.execute("SELECT predicted_winner FROM predictions WHERE match_id = ?", (mid,))
            existing = cursor.fetchone()
            
            if existing:
                pred_winner = existing[0]
                if mode in ["score", "all"]:
                    if is_completed and act_winner is not None:
                        if (act_winner == pred_winner) or (h_team in act_winner and h_team in pred_winner) or (a_team in act_winner and a_team in pred_winner):
                            is_corr = 1
                        else:
                            is_corr = 0
                    else:
                        is_corr = None
                        
                    cursor.execute("""
                    UPDATE predictions SET
                        actual_score_home = ?,
                        actual_score_away = ?,
                        actual_winner = ?,
                        is_correct = ?
                    WHERE match_id = ?
                    """, (act_sc_h, act_sc_a, act_winner, is_corr, mid))
                
                if mode in ["predict", "all"]:
                    pred = get_match_prediction(h_team_std, a_team_std)
                    pred_winner = pred["winner"]
                    cursor.execute("""
                    UPDATE predictions SET
                        home_wuv = ?, away_wuv = ?, home_total_wuv = ?, away_total_wuv = ?,
                        gap = ?, predicted_winner = ?, prob_home = ?, prob_draw = ?, prob_away = ?,
                        score_home = ?, score_away = ?
                    WHERE match_id = ?
                    """, (
                        pred["home_wuv"]["team_wuv"], pred["away_wuv"]["team_wuv"], pred["h_total"], pred["a_total"],
                        pred["gap"], pred_winner, pred["p_home"], pred["p_draw"], pred["p_away"],
                        pred["sc_h"], pred["sc_a"], mid
                    ))
            else:
                pred = get_match_prediction(h_team_std, a_team_std)
                pred_winner = pred["winner"]
                
                if is_completed and act_winner is not None:
                    if (act_winner == pred_winner) or (h_team in act_winner and h_team in pred_winner) or (a_team in act_winner and a_team in pred_winner):
                        is_corr = 1
                    else:
                        is_corr = 0
                else:
                    is_corr = None
                    
                cursor.execute("""
                INSERT INTO predictions (
                    match_id, round_name, home_team, away_team, match_date,
                    home_wuv, away_wuv, home_total_wuv, away_total_wuv,
                    gap, predicted_winner, prob_home, prob_draw, prob_away,
                    score_home, score_away,
                    actual_score_home, actual_score_away, actual_winner, is_correct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    mid, round_label, h_team, a_team, date_raw,
                    pred["home_wuv"]["team_wuv"], pred["away_wuv"]["team_wuv"], pred["h_total"], pred["a_total"],
                    pred["gap"], pred_winner, pred["p_home"], pred["p_draw"], pred["p_away"],
                    pred["sc_h"], pred["sc_a"],
                    act_sc_h, act_sc_a, act_winner, is_corr
                ))

    process_espn_events(resp_mw1.get("events", []), "Round 1 (Gameweek 1)", "MW1")
    process_espn_events(resp_mw2.get("events", []), "Round 2 (Gameweek 2)", "MW2")
    process_espn_events(resp_mw3.get("events", []), "Round 3 (Gameweek 3)", "MW3")

    conn.commit()
    conn.close()
    print("✅ Pipeline run complete! sra_data.db successfully updated.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SRA Pipeline Runner")
    parser.add_argument("--mode", choices=["predict", "score", "all"], default="all", help="Pipeline execution mode")
    args = parser.parse_args()

    print(f"🚀 Serie A (SRA) 정규 시즌 파이프라인 시작 (Mode: {args.mode})", flush=True)
    run_pipeline(mode=args.mode)
