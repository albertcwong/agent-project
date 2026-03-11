#!/usr/bin/env python3
"""Bootstrap script: create a Hyper file with the flag log schema and publish to Tableau Server.

Run with: uv run --extra bootstrap python scripts/bootstrap_flag_log.py
(tableauhyperapi/tableauserverclient are optional deps; agent container does not need them)
"""

import argparse
import os
import sys
from pathlib import Path

DATASOURCE_NAME = "Flag Log"


def _env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "").strip()
    if required and not val:
        print(f"Error: {name} is required", file=sys.stderr)
        sys.exit(1)
    return val


def create_hyper_file(output_path: Path) -> None:
    from tableauhyperapi import (
        Connection,
        CreateMode,
        HyperProcess,
        Nullability,
        SqlType,
        TableDefinition,
        TableName,
        Telemetry,
    )

    table_def = TableDefinition(
        TableName("public", "flag_log"),
        [
            TableDefinition.Column("date_generated", SqlType.date(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("placement", SqlType.text(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("metric", SqlType.text(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("flag_type", SqlType.text(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("direction", SqlType.text(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("value", SqlType.double(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("start_date", SqlType.date(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("end_date", SqlType.date(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("suppressed", SqlType.bool(), Nullability.NOT_NULLABLE),
            TableDefinition.Column("resolved_date", SqlType.date()),
        ],
    )

    with HyperProcess(telemetry=Telemetry.SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(
            hyper.endpoint, str(output_path), CreateMode.CREATE_AND_REPLACE
        ) as conn:
            conn.catalog.create_table(table_def)
    print(f"Created {output_path}")


def publish_to_server(
    hyper_path: Path,
    server_url: str,
    site_id: str,
    project_id: str,
    pat_name: str,
    pat_secret: str,
    overwrite: bool,
    verify_ssl: bool = True,
) -> None:
    import tableauserverclient as TSC

    tableau_auth = TSC.PersonalAccessTokenAuth(pat_name, pat_secret, site_id or "")
    server = TSC.Server(server_url, use_server_version=True)
    if not verify_ssl:
        server.add_http_options({"verify": False})
    server.auth.sign_in(tableau_auth)

    try:
        existing = next(
            (
                d
                for d in server.datasources.filter(name=DATASOURCE_NAME)
                if d.project_id == project_id
            ),
            None,
        )

        if overwrite:
            publish_mode = TSC.Server.PublishMode.Overwrite
            if existing:
                datasource = existing
            else:
                datasource = TSC.DatasourceItem(project_id, name=DATASOURCE_NAME)
                publish_mode = TSC.Server.PublishMode.CreateNew
        else:
            if existing:
                print(
                    f"Datasource '{DATASOURCE_NAME}' already exists in project. Use --overwrite to replace.",
                    file=sys.stderr,
                )
                sys.exit(1)
            datasource = TSC.DatasourceItem(project_id, name=DATASOURCE_NAME)
            publish_mode = TSC.Server.PublishMode.CreateNew

        server.datasources.publish(datasource, str(hyper_path), publish_mode)
        print(f"Published {DATASOURCE_NAME} to Tableau Server")
    finally:
        server.auth.sign_out()


def main() -> None:
    from dotenv import load_dotenv
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")
    load_dotenv(project_root / ".env.flag_log")

    parser = argparse.ArgumentParser(
        description="Create Hyper file with flag log schema and publish to Tableau Server"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("flag_log.hyper"),
        help="Path for .hyper file (default: flag_log.hyper)",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="Create Hyper only, do not publish",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing datasource if present",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL cert verification (for corporate proxies)",
    )
    args = parser.parse_args()

    create_hyper_file(args.output)

    if args.skip_publish:
        print("Skipping publish (--skip-publish)")
        return

    server_url = _env("TABLEAU_SERVER_URL")
    site_id = _env("TABLEAU_SITE_ID", required=False)
    project_id = _env("TABLEAU_PROJECT_ID")
    pat_name = _env("TABLEAU_PAT_NAME")
    pat_secret = _env("TABLEAU_PAT_SECRET")

    verify_ssl = os.environ.get("TABLEAU_SSL_VERIFY", "true").lower() not in ("0", "false", "no")
    if args.no_verify_ssl:
        verify_ssl = False

    publish_to_server(
        args.output,
        server_url,
        site_id,
        project_id,
        pat_name,
        pat_secret,
        args.overwrite,
        verify_ssl=verify_ssl,
    )


if __name__ == "__main__":
    main()
