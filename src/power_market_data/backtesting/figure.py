"""A single self-contained local daily dispatch figure, without a service."""

from importlib import import_module
from pathlib import Path

from power_market_data.backtesting.engine import DayResult
from power_market_data.time import PACIFIC


def write_daily_figure(day: DayResult, output: Path, input_kind: str) -> None:
    go = import_module("plotly.graph_objects")
    figure = import_module("plotly.subplots").make_subplots(rows=3, cols=1, shared_xaxes=True)
    timestamps = [row.interval.start_utc.isoformat() for row in day.inputs]
    local = [row.interval.start_utc.astimezone(PACIFIC).isoformat() for row in day.inputs]
    figure.add_trace(
        go.Scatter(
            x=timestamps,
            y=[float(row.interval.price_usd_per_mwh) for row in day.inputs],
            customdata=local,
            name="LMP (USD/MWh)",
            mode="lines+markers",
            hovertemplate="%{x}<br>Pacific: %{customdata}<br>%{y} USD/MWh",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(x=timestamps, y=day.dispatch.charge_mw, name="Grid charge (MW)"), row=2, col=1
    )
    figure.add_trace(
        go.Bar(
            x=timestamps,
            y=[-v for v in day.dispatch.discharge_mw],
            name="Grid discharge (negative MW)",
        ),
        row=2,
        col=1,
    )
    boundaries = [*timestamps, day.inputs[-1].interval.end_utc.isoformat()]
    figure.add_trace(
        go.Scatter(
            x=boundaries, y=day.dispatch.soc_mwh, name="Boundary SOC (MWh)", mode="lines+markers"
        ),
        row=3,
        col=1,
    )
    figure.update_yaxes(title_text="USD/MWh", row=1, col=1)
    figure.update_yaxes(title_text="Grid MW", row=2, col=1)
    figure.update_yaxes(title_text="MWh", row=3, col=1)
    figure.update_xaxes(title_text="UTC interval start / SOC boundary", row=3, col=1)
    figure.update_layout(
        height=800,
        barmode="relative",
        title=(
            f"Perfect-foresight daily benchmark · {day.market_date} · {day.location}"
            f"<br><sup>{input_kind}; not a deployable policy</sup>"
        ),
    )
    figure.write_html(str(output), include_plotlyjs=True, auto_open=False)
