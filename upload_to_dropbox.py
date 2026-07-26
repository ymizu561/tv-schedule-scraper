#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/ フォルダ内の「本日分」のCSVを、個人Dropboxの
このアプリ専用フォルダ（App folder）へアップロードする。

必要な環境変数（GitHub Secretsから渡す）:
  DROPBOX_APP_KEY
  DROPBOX_APP_SECRET
  DROPBOX_REFRESH_TOKEN

アップロード先は Dropbox内の「アプリ」→「tv-schedule-scraper」フォルダ
（App folder方式のため、他のDropboxデータには一切アクセスしない）。
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import dropbox
from dropbox.files import WriteMode

JST = timezone(timedelta(hours=9))
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def get_today_target_files() -> list[str]:
    """本日（JST）分に関連するファイル名だけを対象にする（毎回全件アップロードしない）。"""
    target_date = datetime.now(JST).strftime("%Y%m%d")
    candidates = [
        f"all_area_programs_{target_date}.csv",
        f"retry_failed_areas_{target_date}.csv",
        "latest.csv",
    ]
    return [c for c in candidates if os.path.exists(os.path.join(OUTPUT_DIR, c))]


def main():
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")

    if not (app_key and app_secret and refresh_token):
        print("⚠️ Dropbox関連のSecretsが設定されていないため、アップロードをスキップします。")
        return 0

    files = get_today_target_files()
    if not files:
        print("⚠️ アップロード対象のファイルが見つかりませんでした。")
        return 0

    dbx = dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )

    for filename in files:
        local_path = os.path.join(OUTPUT_DIR, filename)
        dropbox_path = f"/{filename}"
        with open(local_path, "rb") as f:
            data = f.read()
        dbx.files_upload(data, dropbox_path, mode=WriteMode("overwrite"))
        print(f"✅ Dropboxへアップロード完了: {dropbox_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
