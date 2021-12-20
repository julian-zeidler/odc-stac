"""CLI app for benchmarking."""
import json
import pickle
from datetime import datetime
from typing import Any, Dict, Optional

import click
import distributed
import rasterio.enums

from odc.stac.bench import (
    SAMPLE_SITES,
    BenchLoadParams,
    dump_site,
    load_from_json,
    run_bench,
)

# pylint: disable=too-many-arguments,too-many-locals

RIO_RESAMPLING_NAMES = [it.name for it in rasterio.enums.Resampling]


@click.group("odc-stac-bench")
def main():
    """Benchmarking tool for odc.stac."""


@main.command("prepare")
@click.option("--sample-site", type=str, help="Use one of sample sites")
@click.option(
    "--list-sample-sites",
    is_flag=True,
    default=False,
    help="Print available sample sites",
)
@click.option(
    "--from-file",
    help="From json config file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option("--overwrite", is_flag=True, help="Overwite output file")
def prepare(sample_site, list_sample_sites, from_file, overwrite):
    """Prepare benchmarking dataset."""
    if list_sample_sites:
        click.echo("Sample sites:")
        for site_name in SAMPLE_SITES:
            click.echo(f"   {site_name}")
        return

    site: Optional[Dict[str, Any]] = None
    if sample_site is not None:
        site = SAMPLE_SITES.get(sample_site, None)
        if site is None:
            raise click.ClickException(f"No such site: {sample_site}")
        print("Site config:")
        print("------------------------------------------")
        print(json.dumps(site, indent=2))
        print("------------------------------------------")
    elif from_file is not None:
        with open(from_file, "rt", encoding="utf8") as src:
            site = json.load(src)

    if site is None:
        raise click.ClickException("Have to supply one of --sample-site or --from-file")
    dump_site(site, overwrite=overwrite)


@main.command("dask")
def _dask():
    """Launch local Dask Cluster."""
    print("TODO")


@main.command("run")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    required=False,
    help="GeoJSON file generated with `prepare` step.",
)
@click.option(
    "--ntimes", "-n", type=int, default=1, help="Configure number of times to run"
)
@click.option(
    "--method",
    help="Data loading method",
    type=click.Choice(["odc-stac", "stackstac"]),
)
@click.option("--bands", type=str, help="Comma separated list of bands")
@click.option("--chunks", type=int, help="Chunk size Y,X order", nargs=2)
@click.option("--resolution", type=float, help="Set output resolution")
@click.option("--crs", type=str, help="Set CRS")
@click.option(
    "--resampling",
    help="Resampling method when changing resolution/projection",
    type=click.Choice(RIO_RESAMPLING_NAMES),
)
@click.option("--show-config", is_flag=True, help="Show configuration only, don't run")
@click.option(
    "--scheduler", default="tcp://localhost:8786", help="Dask server to connect to"
)
@click.argument("site", type=click.Path(exists=True, dir_okay=False, readable=True))
def run(
    site,
    config,
    method,
    ntimes,
    bands,
    chunks,
    resolution,
    crs,
    resampling,
    show_config,
    scheduler,
):
    """Run data load benchmark using Dask."""
    cfg: Optional[BenchLoadParams] = None
    if config is not None:
        with open(config, "rt", encoding="utf8") as src:
            cfg = BenchLoadParams.from_json(src.read())
    else:
        cfg = BenchLoadParams(
            method="odc-stac",
            chunks=(2048, 2048),
            extra={
                "stackstac": {"dtype": "uint16", "fill_value": 0},
                "odc-stac": {
                    "groupby": "solar_day",
                    "stac_cfg": {"*": {"warnings": "ignore"}},
                },
            },
        )

    if chunks:
        cfg.chunks = chunks
    if method is not None:
        cfg.method = method
    if bands is not None:
        cfg.bands = tuple(bands.split(","))
    if resolution is not None:
        cfg.resolution = resolution
    if crs is not None:
        cfg.crs = crs
    if resampling is not None:
        cfg.resampling = resampling
    if not cfg.scenario:
        cfg.scenario = site.rsplit(".", 1)[0]

    with open(site, "rt", encoding="utf8") as src:
        site_geojson = json.load(src)

    print(f"Loaded: {len(site_geojson['features'])} STAC items from '{site}'")

    print("Will use following load configuration")
    print("-" * 60)
    print(cfg.to_json(indent=2))
    print("-" * 60)

    if show_config:
        return

    print(f"Connecting to Dask Scheduler: {scheduler}")
    client = distributed.Client(scheduler)

    print("Constructing Dask graph")
    xx = load_from_json(site_geojson, cfg)
    print(f"Starting benchmark run ({ntimes} runs)")
    print("=" * 60)

    bench_ctx, samples = run_bench(xx, client, ntimes=ntimes)
    print("=" * 60)
    print("Finsihed")
    ts = datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    results_file = f"{cfg.scenario}_{ts}.pkl"
    print(f"Saving results to: {results_file}")
    with open(results_file, "wb") as dst:
        pickle.dump({"context": bench_ctx, "samples": samples}, dst)


@main.command("report")
def report():
    """Assemble report."""
    print("TODO")
