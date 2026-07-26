#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国テレビ番組表 自動取得スクリプト（GitHub Actions版）

概要:
  番組表.Gガイド（bangumi.org）から、全国54エリアの地上波番組表を取得し、
  CSVとして data/ ディレクトリに保存する。

  元のスクリプト（Selenium + Chromeヘッドレス）から、以下を変更している:
    - Seleniumではなく requests を使用（対象ページはJS不要の静的HTMLのため、
      ブラウザを起動する必要がない。速く・軽く・依存関係も少ない）。
    - 出力先を GitHub Actions のワークスペース内 data/ フォルダに変更
      （Macのローカルパスへの依存をなくし、launchd権限問題を解消）。
    - 実行日をJST（日本時間）基準で計算（GitHub Actionsの実行環境はUTCのため）。

  データ形式（列）は元スクリプトと同一:
    放送エリア, 放送局, 放送日, 放送時間, 番組名
"""

import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# ===== 設定 =====

JST = timezone(timedelta(hours=9))

# 何日分取得するか（0=今日のみ）。必要なら増やせる。
DAYS_TO_FETCH = [0]

# 取得先ディレクトリ（リポジトリ内。GitHub Actionsがそのままコミットする）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

REQUEST_TIMEOUT = 15  # 秒
REQUEST_INTERVAL = 1.0  # 各エリア取得の間隔（サイトに負荷をかけすぎないため）
MAX_RETRIES_PER_AREA = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# 地域IDマップ（元スクリプトと同一）
AREA_MAP = {
    "札幌": "1", "函館": "8", "旭川": "3", "帯広": "9", "釧路": "10", "北見": "12", "室蘭": "6",
    "青森": "13", "岩手": "16", "宮城": "19", "秋田": "22", "山形": "25", "福島": "28", "東京": "42",
    "神奈川": "45", "埼玉": "37", "千葉": "40", "茨城": "31", "栃木": "33", "群馬": "35",
    "山梨": "50", "長野": "51", "新潟": "56", "愛知": "73", "石川": "60", "静岡": "67", "福井": "62",
    "富山": "58", "三重": "76", "岐阜": "64", "大阪": "84", "京都": "81", "兵庫": "85", "和歌山": "93",
    "奈良": "91", "滋賀": "79", "広島": "101", "岡山": "98", "島根": "96", "鳥取": "95", "山口": "105",
    "愛媛": "112", "香川": "110", "徳島": "109", "高知": "116", "福岡": "117", "熊本": "126", "長崎": "123",
    "鹿児島": "131", "宮崎": "129", "大分": "127", "佐賀": "122", "沖縄": "134", "北九州": "120",
}


def fetch_html(session: requests.Session, url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES_PER_AREA + 2):
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            print(f"    ⚠️ 取得失敗（{attempt}回目）: {exc}")
            time.sleep(2)
    return None


def parse_area(html: str, area_name: str, station_filter_date: str):
    """1エリア分のHTMLから番組情報を抽出する。元スクリプトと同じセレクタを使用。"""
    soup = BeautifulSoup(html, "html.parser")

    station_tags = soup.select("li.js_channel.topmost p")
    station_names = [tag.text.strip() for tag in station_tags]

    program_ul_tags = soup.select("ul[id^=program_line_]")
    program_ids = [int(ul.get("id").split("_")[-1]) for ul in program_ul_tags if ul.get("id")]

    if not station_names or not program_ids:
        return None  # 取得失敗 or ページ構造が変わった

    program_index_base = min(program_ids)
    rows = []

    for i, station in enumerate(station_names):
        program_index = program_index_base + i
        selector = (
            f"#program_line_{program_index} li.sc-past, "
            f"#program_line_{program_index} li.sc-current, "
            f"#program_line_{program_index} li.sc-future"
        )
        programs = soup.select(selector)

        for prog in programs:
            start = prog.get("s")
            title_tag = prog.select_one("p.program_title")
            if start and title_tag and start.startswith(station_filter_date):
                time_str = f"{start[8:10]}:{start[10:12]}"
                title = title_tag.text.strip()
                rows.append([
                    area_name,
                    station,
                    f"{station_filter_date[:4]}-{station_filter_date[4:6]}-{station_filter_date[6:]}",
                    time_str,
                    title,
                ])

    return rows


def scrape_for_date(session: requests.Session, target_date: str):
    """target_date（YYYYMMDD）の全国データを取得する。"""
    results = []
    failed_areas = []

    for area_name, area_id in AREA_MAP.items():
        print(f"▶ 処理中：{area_name}（ID: {area_id}, 日付: {target_date}）")
        url = f"https://bangumi.org/epg/td?broad_cast_date={target_date}&ggm_group_id={area_id}"
        html = fetch_html(session, url)

        if html is None:
            print(f"  ⚠️ エラー：{area_name} をスキップ（通信失敗）")
            failed_areas.append((area_name, area_id))
            time.sleep(REQUEST_INTERVAL)
            continue

        rows = parse_area(html, area_name, target_date)
        if rows is None:
            print(f"  ⚠️ スキップ：{area_name} に番組データなし（ページ構造変化の可能性）")
            failed_areas.append((area_name, area_id))
        else:
            results.extend(rows)
            print(f"  ✅ {area_name}: {len(rows)}件取得")

        time.sleep(REQUEST_INTERVAL)

    return results, failed_areas


def write_csv(path: str, rows: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["放送エリア", "放送局", "放送日", "放送時間", "番組名"])
        writer.writerows(rows)


def main():
    now_jst = datetime.now(JST)
    session = requests.Session()

    any_failures = False

    for offset in DAYS_TO_FETCH:
        target_date = (now_jst + timedelta(days=offset)).strftime("%Y%m%d")
        print(f"\n===== {target_date} の番組表を取得します =====")

        results, failed_areas = scrape_for_date(session, target_date)

        output_file = os.path.join(OUTPUT_DIR, f"all_area_programs_{target_date}.csv")
        write_csv(output_file, results)
        print(f"\n✅ 出力完了：{output_file}（{len(results)}件）")

        # 最新版として latest.csv も更新（他メンバーが常に最新を見つけやすいように）
        latest_file = os.path.join(OUTPUT_DIR, "latest.csv")
        write_csv(latest_file, results)

        if failed_areas:
            any_failures = True
            print(f"\n🔁 再トライ中... 対象: {[a for a, _ in failed_areas]}")
            # 失敗エリアのみ再取得
            retry_results = []
            still_failed = []
            for area_name, area_id in failed_areas:
                print(f"🔁 再取得：{area_name}")
                url = f"https://bangumi.org/epg/td?broad_cast_date={target_date}&ggm_group_id={area_id}"
                html = fetch_html(session, url)
                if html is None:
                    still_failed.append(area_name)
                    continue
                rows = parse_area(html, area_name, target_date)
                if rows is None:
                    still_failed.append(area_name)
                else:
                    retry_results.extend(rows)
                time.sleep(REQUEST_INTERVAL)

            if retry_results:
                # 成功した分は本体CSVにも追記し、latestも更新
                results.extend(retry_results)
                write_csv(output_file, results)
                write_csv(latest_file, results)

            retry_file = os.path.join(OUTPUT_DIR, f"retry_failed_areas_{target_date}.csv")
            with open(retry_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["再トライ後も失敗したエリア"])
                for name in still_failed:
                    writer.writerow([name])

            if still_failed:
                print(f"❌ 再トライ後も失敗：{still_failed}")
            print(f"✅ 再トライ結果反映済み：{retry_file}")

    if any_failures:
        # 失敗があってもワークフロー自体は失敗させない（部分成功データは活用できるため）
        print("\n⚠️ 一部エリアの取得に失敗しました。ログを確認してください。")

    print("\n完了。")


if __name__ == "__main__":
    sys.exit(main())
