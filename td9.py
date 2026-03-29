#!/usr/bin/env python3
"""
TD9 Sequential Indicator (Yata-style)
======================================
Standalone Python implementation of the CC • Yata TradingView Pine Script indicator.

TD9 logic based on CC • Yata Pine Script indicator (MPL 2.0)
https://mozilla.org/MPL/2.0/

Features:
  - TD Setup (1-9): Buy setup (9 consecutive closes < close[4]) and Sell setup (close > close[4])
  - TD Countdown (1-13): Standard and Aggressive modes
  - Support/Resistance levels from completed 9-counts
  - Stealth 9 detection
  - RSI (14) and MACD (12,26,9) panels
  - Interactive candlestick chart with all signals overlaid

Dependencies:
  pip install yfinance mplfinance matplotlib pandas numpy

Usage:
  python td9.py AAPL                    # Daily chart, last 200 bars
  python td9.py GME -p 1h -n 300       # 1-hour chart, 300 bars
  python td9.py SPY -p 1wk             # Weekly chart
  python td9.py BABA --mode aggressive  # Aggressive countdown mode
  python td9.py NXPI --show 1to9       # Show all setup counts 1-9
  python td9.py NXPI --show 6to9       # Show counts 6-9 (default)
  python td9.py NXPI --show 789        # Show counts 7, 8, and 9
  python td9.py NXPI --show 89         # Show counts 8 and 9
  python td9.py NXPI --show only9      # Show only completed 9s
  python td9.py NXPI --show none       # Hide all setup numbers
  python td9.py GME --no-countdown      # Setup only, no countdown overlay
  python td9.py SPY --no-sr             # Hide support/resistance lines
  python td9.py SPY --stealth           # Enable stealth 9 detection
  python td9.py GME --no-chart          # Text summary only, no chart
  python td9.py GME --td                # Print only the current TD number
  python td9.py GME --no-rsi            # Hide RSI panel
  python td9.py GME --no-macd           # Hide MACD panel
  python td9.py GME --no-rsi --no-macd  # Hide both indicator panels
  python td9.py AAPL -o my_chart.png    # Custom output file path
"""

import argparse
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import mplfinance as mpf


# ─────────────────────────────────────────────
# TD Setup (1–9)
# ─────────────────────────────────────────────

def compute_td_setup(df):
    """
    Compute TD Sequential Setup counts.
    Buy Setup:  close < close[4] for 9 consecutive bars (counts 1-9, resets after 9)
    Sell Setup: close > close[4] for 9 consecutive bars (counts 1-9, resets after 9)
    """
    n = len(df)
    buy_setup = np.zeros(n, dtype=int)
    sell_setup = np.zeros(n, dtype=int)

    for i in range(4, n):
        # Sell setup: close > close[4]
        if df["Close"].iloc[i] > df["Close"].iloc[i - 4]:
            prev = sell_setup[i - 1]
            sell_setup[i] = 1 if prev == 9 else prev + 1
        else:
            sell_setup[i] = 0

        # Buy setup: close < close[4]
        if df["Close"].iloc[i] < df["Close"].iloc[i - 4]:
            prev = buy_setup[i - 1]
            buy_setup[i] = 1 if prev == 9 else prev + 1
        else:
            buy_setup[i] = 0

    df["buy_setup"] = buy_setup
    df["sell_setup"] = sell_setup
    return df


# ─────────────────────────────────────────────
# Support / Resistance from completed 9-counts
# ─────────────────────────────────────────────

def compute_support_resistance(df):
    """
    After a buy setup 9: resistance = highest high of last 9 bars.
      Cleared when close > resistance.
    After a sell setup 9: support = lowest low of last 9 bars.
      Cleared when close < support.
    """
    n = len(df)
    high_trend = np.zeros(n)
    low_trend = np.zeros(n)

    for i in range(n):
        if i < 8:
            high_trend[i] = 0.0
            low_trend[i] = 0.0
            continue

        # Resistance from buy setup 9
        if df["buy_setup"].iloc[i] == 9:
            high_trend[i] = df["High"].iloc[i - 8 : i + 1].max()
        elif df["Close"].iloc[i] > high_trend[i - 1]:
            high_trend[i] = 0.0
        else:
            high_trend[i] = high_trend[i - 1]

        # Support from sell setup 9
        if df["sell_setup"].iloc[i] == 9:
            low_trend[i] = df["Low"].iloc[i - 8 : i + 1].min()
        elif df["Close"].iloc[i] < low_trend[i - 1]:
            low_trend[i] = 0.0
        else:
            low_trend[i] = low_trend[i - 1]

    df["resistance"] = high_trend
    df["support"] = low_trend
    df["resistance"] = df["resistance"].replace(0.0, np.nan)
    df["support"] = df["support"].replace(0.0, np.nan)
    return df


# ─────────────────────────────────────────────
# TD Countdown (1–13) — Standard mode
# ─────────────────────────────────────────────

def compute_standard_countdown(df):
    """
    Standard Countdown:
      Buy Countdown:  close < low[2], starts after buy setup 9, resets on sell setup 9 or resistance cleared.
        Bar 13 qualification: low of bar 13 must be > close of bar 8.
      Sell Countdown: close > high[2], starts after sell setup 9, resets on buy setup 9 or support cleared.
        Bar 13 qualification: high of bar 13 must be < close of bar 8.
    """
    n = len(df)
    buy_cd = np.zeros(n)
    sell_cd = np.zeros(n)
    buy_cd8_close = np.zeros(n)
    sell_cd8_close = np.zeros(n)

    for i in range(2, n):
        # --- Buy countdown ---
        is_buy_cd = df["Close"].iloc[i] < df["Low"].iloc[i - 2]
        prev_buy = abs(buy_cd[i - 1])

        if df["buy_setup"].iloc[i] == 9:
            buy_cd[i] = 1 if is_buy_cd else 0
        elif df["sell_setup"].iloc[i] == 9 or (df["resistance"].iloc[i] != df["resistance"].iloc[i] ):  # NaN check = cleared
            # Check if resistance just became NaN (was cleared)
            res_cleared = (not np.isnan(df["resistance"].iloc[i - 1]) if i > 0 else False) and np.isnan(df["resistance"].iloc[i])
            if df["sell_setup"].iloc[i] == 9 or res_cleared:
                buy_cd[i] = 14  # sentinel: inactive
            else:
                # Non-qualified 13 check
                non_q = is_buy_cd and prev_buy == 12 and df["Low"].iloc[i] > buy_cd8_close[i - 1]
                if non_q:
                    buy_cd[i] = -12  # non-qualified, restart from 12
                elif is_buy_cd:
                    buy_cd[i] = prev_buy + 1
                else:
                    buy_cd[i] = -prev_buy  # negative = paused at this count
        else:
            non_q = is_buy_cd and prev_buy == 12 and df["Low"].iloc[i] > buy_cd8_close[i - 1]
            if non_q:
                buy_cd[i] = -12
            elif is_buy_cd:
                buy_cd[i] = prev_buy + 1
            else:
                buy_cd[i] = -prev_buy

        buy_cd8_close[i] = df["Close"].iloc[i] if buy_cd[i] == 8 else buy_cd8_close[i - 1]

        # --- Sell countdown ---
        is_sell_cd = df["Close"].iloc[i] > df["High"].iloc[i - 2]
        prev_sell = abs(sell_cd[i - 1])

        if df["sell_setup"].iloc[i] == 9:
            sell_cd[i] = 1 if is_sell_cd else 0
        elif df["buy_setup"].iloc[i] == 9:
            sell_cd[i] = 14
        else:
            sup_cleared = (not np.isnan(df["support"].iloc[i - 1]) if i > 0 else False) and np.isnan(df["support"].iloc[i])
            if sup_cleared:
                sell_cd[i] = 14
            else:
                non_q = is_sell_cd and prev_sell == 12 and df["High"].iloc[i] < sell_cd8_close[i - 1]
                if non_q:
                    sell_cd[i] = -12
                elif is_sell_cd:
                    sell_cd[i] = prev_sell + 1
                else:
                    sell_cd[i] = -prev_sell

        sell_cd8_close[i] = df["Close"].iloc[i] if sell_cd[i] == 8 else sell_cd8_close[i - 1]

    df["buy_countdown"] = buy_cd.astype(int)
    df["sell_countdown"] = sell_cd.astype(int)
    return df


# ─────────────────────────────────────────────
# TD Countdown — Aggressive mode
# ─────────────────────────────────────────────

def compute_aggressive_countdown(df):
    """
    Aggressive Countdown:
      Buy:  low < low[2] (instead of close < low[2])
      Sell: high > high[2] (instead of close > high[2])
      No bar-13 qualification check.
    """
    n = len(df)
    agg_buy = np.zeros(n)
    agg_sell = np.zeros(n)

    for i in range(2, n):
        is_agg_buy = df["Low"].iloc[i] < df["Low"].iloc[i - 2]
        prev_buy = abs(agg_buy[i - 1])

        if df["buy_setup"].iloc[i] == 9:
            agg_buy[i] = 1 if is_agg_buy else 0
        elif df["sell_setup"].iloc[i] == 9:
            agg_buy[i] = 14
        else:
            res_cleared = (not np.isnan(df["resistance"].iloc[i - 1]) if i > 0 else False) and np.isnan(df["resistance"].iloc[i])
            if res_cleared:
                agg_buy[i] = 14
            elif is_agg_buy:
                agg_buy[i] = prev_buy + 1
            else:
                agg_buy[i] = -prev_buy

        is_agg_sell = df["High"].iloc[i] > df["High"].iloc[i - 2]
        prev_sell = abs(agg_sell[i - 1])

        if df["sell_setup"].iloc[i] == 9:
            agg_sell[i] = 1 if is_agg_sell else 0
        elif df["buy_setup"].iloc[i] == 9:
            agg_sell[i] = 14
        else:
            sup_cleared = (not np.isnan(df["support"].iloc[i - 1]) if i > 0 else False) and np.isnan(df["support"].iloc[i])
            if sup_cleared:
                agg_sell[i] = 14
            elif is_agg_sell:
                agg_sell[i] = prev_sell + 1
            else:
                agg_sell[i] = -prev_sell

    df["agg_buy_countdown"] = agg_buy.astype(int)
    df["agg_sell_countdown"] = agg_sell.astype(int)
    return df


# ─────────────────────────────────────────────
# Stealth 9
# ─────────────────────────────────────────────

def compute_stealth9(df):
    """
    Stealth Buy 9:  within 1 bar of buy_setup == 8, sell_setup == 1
    Stealth Sell 9: within 1 bar of sell_setup == 8, buy_setup == 1
    """
    n = len(df)
    stealth_buy = np.zeros(n, dtype=bool)
    stealth_sell = np.zeros(n, dtype=bool)

    for i in range(1, n):
        # bars since buy_setup == 8 (check current and previous bar)
        buy8_recent = (df["buy_setup"].iloc[i] == 8) or (df["buy_setup"].iloc[i - 1] == 8)
        sell8_recent = (df["sell_setup"].iloc[i] == 8) or (df["sell_setup"].iloc[i - 1] == 8)

        stealth_buy[i] = buy8_recent and df["sell_setup"].iloc[i] == 1
        stealth_sell[i] = sell8_recent and df["buy_setup"].iloc[i] == 1

    df["stealth_buy"] = stealth_buy
    df["stealth_sell"] = stealth_sell
    return df


# ─────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────

def compute_rsi(df, period=14):
    """Compute RSI (Relative Strength Index) using Wilder's smoothing."""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ─────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────

def compute_macd(df, fast=12, slow=26, signal=9):
    """Compute MACD line, signal line, and histogram."""
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


# ─────────────────────────────────────────────
# Run all computations
# ─────────────────────────────────────────────

def compute_all(df):
    df = compute_td_setup(df)
    df = compute_support_resistance(df)
    df = compute_standard_countdown(df)
    df = compute_aggressive_countdown(df)
    df = compute_stealth9(df)
    df = compute_rsi(df)
    df = compute_macd(df)
    return df


# ─────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────

PERIOD_MAP = {
    "1m": ("7d", "1m"),
    "2m": ("7d", "2m"),
    "5m": ("60d", "5m"),
    "15m": ("60d", "15m"),
    "30m": ("60d", "30m"),
    "1h": ("730d", "1h"),
    "4h": ("730d", "1h"),  # yfinance doesn't support 4h natively; we resample
    "8h": ("730d", "1h"),  # same — resample from 1h
    "1d": ("10y", "1d"),
    "1wk": ("10y", "1wk"),
    "1mo": ("max", "1mo"),
}


def fetch_data(ticker, period_key="1d", num_bars=200, quiet=False):
    """Download OHLCV data via yfinance."""
    if period_key not in PERIOD_MAP:
        print(f"Unsupported period '{period_key}'. Choose from: {list(PERIOD_MAP.keys())}")
        sys.exit(1)

    yf_period, yf_interval = PERIOD_MAP[period_key]
    needs_resample = period_key in ("4h", "8h")

    if not quiet:
        print(f"Fetching {ticker} data ({period_key} timeframe)...")
    data = yf.download(ticker, period=yf_period, interval=yf_interval, progress=False)

    if data.empty:
        print(f"No data returned for {ticker}. Check the ticker symbol.")
        sys.exit(1)

    # Flatten multi-level columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if needs_resample:
        rule = "4h" if period_key == "4h" else "8h"
        data = data.resample(rule).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()

    # Take last N bars (plus buffer for lookback)
    buffer = num_bars + 50
    data = data.tail(buffer)
    return data


# ─────────────────────────────────────────────
# Chart rendering
# ─────────────────────────────────────────────

def get_setup_visibility(show_mode, count):
    """Return True if this setup count should be visible given the show mode."""
    if show_mode == "1to9":
        return True
    elif show_mode == "6to9":
        return count >= 6
    elif show_mode == "789":
        return count >= 7
    elif show_mode == "89":
        return count >= 8
    elif show_mode == "only9":
        return count == 9
    elif show_mode == "none":
        return False
    return count >= 6  # default


def plot_chart(df, ticker, period_key, show_mode="6to9", mode="standard",
               show_countdown=True, show_sr=True, show_stealth=False,
               show_rsi=True, show_macd=True, output_file=None):
    """Render candlestick chart with TD9 signals using mplfinance."""

    # Trim to display range (remove buffer bars)
    plot_df = df.copy()

    # Prepare additional plots
    add_plots = []

    # Colors matching the Pine Script
    buy_colors_setup = {
        1: "#1C61B1", 2: "#1D80AF", 3: "#1D80AF", 4: "#1EA9AC", 5: "#1EA9AC",
        6: "#34BEA5", 7: "#34BEA5", 8: "#67D89A", 9: "#90EE90",
    }
    sell_colors_setup = {
        1: "#69208E", 2: "#9138A7", 3: "#9138A7", 4: "#CA3AB0", 5: "#CA3AB0",
        6: "#F23D92", 7: "#F23D92", 8: "#F71746", 9: "#E21B22",
    }

    # We'll use matplotlib annotations after the mplfinance plot
    # First, create the base chart

    # Support/Resistance
    if show_sr:
        sup_series = plot_df["support"].copy()
        res_series = plot_df["resistance"].copy()
        if sup_series.notna().any():
            add_plots.append(mpf.make_addplot(sup_series, type="scatter", markersize=8,
                                              marker="o", color="#90EE90", alpha=0.75))
        if res_series.notna().any():
            add_plots.append(mpf.make_addplot(res_series, type="scatter", markersize=8,
                                              marker="o", color="#E21B22", alpha=0.75))

    # RSI panel
    if show_rsi and "rsi" in plot_df.columns:
        rsi_panel = 2  # panel 0 = price, 1 = volume, 2+ = additional
        # RSI overbought/oversold reference lines
        rsi_70 = pd.Series(70.0, index=plot_df.index)
        rsi_30 = pd.Series(30.0, index=plot_df.index)
        add_plots.append(mpf.make_addplot(plot_df["rsi"], panel=rsi_panel, color="#E040FB",
                                          width=1.2, ylabel="RSI"))
        add_plots.append(mpf.make_addplot(rsi_70, panel=rsi_panel, color="#FF5252",
                                          width=0.5, linestyle="--", alpha=0.5))
        add_plots.append(mpf.make_addplot(rsi_30, panel=rsi_panel, color="#4CAF50",
                                          width=0.5, linestyle="--", alpha=0.5))

    # MACD panel
    if show_macd and "macd" in plot_df.columns:
        macd_panel = 3 if show_rsi else 2
        hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in plot_df["macd_hist"].fillna(0)]
        add_plots.append(mpf.make_addplot(plot_df["macd"], panel=macd_panel, color="#2196F3",
                                          width=1.0, ylabel="MACD"))
        add_plots.append(mpf.make_addplot(plot_df["macd_signal"], panel=macd_panel, color="#FF9800",
                                          width=1.0))
        add_plots.append(mpf.make_addplot(plot_df["macd_hist"], panel=macd_panel, type="bar",
                                          color=hist_colors, width=0.7, alpha=0.6))

    # Chart style
    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350",
        edge={"up": "#26a69a", "down": "#ef5350"},
        wick={"up": "#26a69a", "down": "#ef5350"},
        volume={"up": "#26a69a80", "down": "#ef535080"},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style="nightclouds",
        facecolor="#131722",
        figcolor="#131722",
        gridcolor="#1e222d",
        gridstyle="-",
        gridaxis="both",
        y_on_right=True,
        rc={"font.size": 8},
    )

    # Calculate figure height based on active panels
    num_panels = 2  # price + volume
    if show_rsi:
        num_panels += 1
    if show_macd:
        num_panels += 1
    fig_height = 8 + (num_panels - 2) * 2.5  # base 8 for price+vol, 2.5 per extra panel

    # Panel ratios: price gets the most space
    panel_ratios = [4, 1]  # price, volume
    if show_rsi:
        panel_ratios.append(1.5)
    if show_macd:
        panel_ratios.append(1.5)

    fig, axes = mpf.plot(
        plot_df,
        type="candle",
        style=style,
        volume=True,
        addplot=add_plots if add_plots else None,
        figsize=(20, fig_height),
        returnfig=True,
        tight_layout=True,
        panel_ratios=panel_ratios,
        datetime_format="%b %d" if period_key in ("1d", "1wk", "1mo") else "%m/%d %H:%M",
    )

    ax = axes[0]  # price axis

    # Compute price range for offset calculations
    price_min = plot_df["Low"].min()
    price_max = plot_df["High"].max()
    price_range = price_max - price_min
    offset_buy = price_range * 0.018
    offset_sell = price_range * 0.018
    offset_cd_buy = price_range * 0.040
    offset_cd_sell = price_range * 0.040

    x_positions = range(len(plot_df))

    # --- Plot Setup Numbers ---
    for idx, (i, row) in enumerate(plot_df.iterrows()):
        x = idx

        # Buy setup
        bs = int(row["buy_setup"])
        if bs > 0 and get_setup_visibility(show_mode, bs):
            color = buy_colors_setup.get(bs, "#34BEA5")
            alpha = 0.3 + (bs / 9) * 0.7
            fontsize = 7 if bs < 8 else (8 if bs == 8 else 10)
            fontweight = "normal" if bs < 9 else "bold"
            ax.annotate(
                str(bs), xy=(x, row["Low"] - offset_buy),
                fontsize=fontsize, fontweight=fontweight,
                color=color, alpha=alpha,
                ha="center", va="top",
            )

        # Sell setup
        ss = int(row["sell_setup"])
        if ss > 0 and get_setup_visibility(show_mode, ss):
            color = sell_colors_setup.get(ss, "#F23D92")
            alpha = 0.3 + (ss / 9) * 0.7
            fontsize = 7 if ss < 8 else (8 if ss == 8 else 10)
            fontweight = "normal" if ss < 9 else "bold"
            ax.annotate(
                str(ss), xy=(x, row["High"] + offset_sell),
                fontsize=fontsize, fontweight=fontweight,
                color=color, alpha=alpha,
                ha="center", va="bottom",
            )

        # Stealth 9
        if show_stealth:
            if row.get("stealth_buy", False):
                ax.annotate(
                    "s9", xy=(x, row["Low"] - offset_buy),
                    fontsize=9, fontweight="bold",
                    color="#90EE90", alpha=0.8,
                    ha="center", va="top",
                )
            if row.get("stealth_sell", False):
                ax.annotate(
                    "s9", xy=(x, row["High"] + offset_sell),
                    fontsize=9, fontweight="bold",
                    color="#E21B22", alpha=0.8,
                    ha="center", va="top",
                )

    # --- Plot Countdown Numbers ---
    if show_countdown:
        buy_cd_col = "buy_countdown" if mode == "standard" else "agg_buy_countdown"
        sell_cd_col = "sell_countdown" if mode == "standard" else "agg_sell_countdown"

        for idx, (i, row) in enumerate(plot_df.iterrows()):
            x = idx

            bcd = int(row[buy_cd_col])
            if 1 <= bcd <= 13:
                alpha = 0.25 + (bcd / 13) * 0.75
                fontsize = 6 if bcd < 12 else (8 if bcd == 12 else 10)
                color = "#4CAF50" if bcd < 13 else "#00FF00"
                fontweight = "bold" if bcd == 13 else "normal"
                ax.annotate(
                    str(bcd), xy=(x, row["Low"] - offset_cd_buy),
                    fontsize=fontsize, fontweight=fontweight,
                    color=color, alpha=alpha,
                    ha="center", va="top",
                )

            scd = int(row[sell_cd_col])
            if 1 <= scd <= 13:
                alpha = 0.25 + (scd / 13) * 0.75
                fontsize = 6 if scd < 12 else (8 if scd == 12 else 10)
                color = "#FF5252" if scd < 13 else "#FF0000"
                fontweight = "bold" if scd == 13 else "normal"
                ax.annotate(
                    str(scd), xy=(x, row["High"] + offset_cd_sell),
                    fontsize=fontsize, fontweight=fontweight,
                    color=color, alpha=alpha,
                    ha="center", va="bottom",
                )

    # Title
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title_str = f"{ticker.upper()}  •  TD9 Sequential ({period_key})  •  {mode.capitalize()} Mode  •  {now}"
    ax.set_title(title_str, fontsize=12, fontweight="bold", color="white", pad=15)

    # Legend
    legend_text = []
    legend_text.append("Setup: green=buy, purple/red=sell")
    if show_countdown:
        legend_text.append(f"Countdown ({mode}): green=buy, red=sell")
    if show_sr:
        legend_text.append("S/R: green●=support, red●=resistance")
    if show_rsi:
        legend_text.append("RSI(14)")
    if show_macd:
        legend_text.append("MACD(12,26,9)")
    ax.text(
        0.01, 0.98, "  |  ".join(legend_text),
        transform=ax.transAxes, fontsize=7, color="#888888",
        verticalalignment="top",
    )

    date_str = datetime.now().strftime("%Y%m%d")
    out = output_file or f"td9_{ticker.lower()}_{period_key}_{date_str}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    print(f"Chart saved: {out}")
    return out


# ─────────────────────────────────────────────
# Print summary table
# ─────────────────────────────────────────────

def print_summary(df, ticker, mode="standard"):
    """Print a text summary of current TD9 state and recent signals."""
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    print(f"\n{'=' * 60}")
    print(f"  TD9 SEQUENTIAL — {ticker.upper()}")
    print(f"{'=' * 60}")
    print(f"  Last Close:  ${last['Close']:.2f}")
    print(f"  Last High:   ${last['High']:.2f}")
    print(f"  Last Low:    ${last['Low']:.2f}")
    print()

    # Current setup
    if last["buy_setup"] > 0:
        print(f"  Buy Setup:   {int(last['buy_setup'])} / 9")
    elif last["sell_setup"] > 0:
        print(f"  Sell Setup:  {int(last['sell_setup'])} / 9")
    else:
        print(f"  Setup:       None active")

    # Current countdown
    buy_cd_col = "buy_countdown" if mode == "standard" else "agg_buy_countdown"
    sell_cd_col = "sell_countdown" if mode == "standard" else "agg_sell_countdown"

    bcd = int(last[buy_cd_col])
    scd = int(last[sell_cd_col])

    if 1 <= bcd <= 13:
        print(f"  Buy Countdown:  {bcd} / 13 ({mode})")
    if 1 <= scd <= 13:
        print(f"  Sell Countdown: {scd} / 13 ({mode})")

    # S/R
    if not np.isnan(last.get("support", np.nan)):
        print(f"  Support:     ${last['support']:.2f}")
    if not np.isnan(last.get("resistance", np.nan)):
        print(f"  Resistance:  ${last['resistance']:.2f}")

    # Recent 9s
    print(f"\n  Recent Completed Setups (last 50 bars):")
    tail = df.tail(50)
    found = False
    for i, row in tail.iterrows():
        if row["buy_setup"] == 9:
            print(f"    Buy 9  @ {i}  Close=${row['Close']:.2f}")
            found = True
        if row["sell_setup"] == 9:
            print(f"    Sell 9 @ {i}  Close=${row['Close']:.2f}")
            found = True
    if not found:
        print("    None in last 50 bars")

    # Recent 13s
    print(f"\n  Recent Completed Countdowns (last 50 bars):")
    found = False
    for i, row in tail.iterrows():
        if int(row[buy_cd_col]) == 13:
            print(f"    Buy 13  @ {i}  Close=${row['Close']:.2f}")
            found = True
        if int(row[sell_cd_col]) == 13:
            print(f"    Sell 13 @ {i}  Close=${row['Close']:.2f}")
            found = True
    if not found:
        print("    None in last 50 bars")

    # RSI / MACD
    if "rsi" in last.index and not np.isnan(last.get("rsi", np.nan)):
        rsi_val = last["rsi"]
        rsi_status = "OVERBOUGHT" if rsi_val >= 70 else "OVERSOLD" if rsi_val <= 30 else ""
        print(f"  RSI(14):     {rsi_val:.1f}  {rsi_status}")
    if "macd" in last.index and not np.isnan(last.get("macd", np.nan)):
        macd_val = last["macd"]
        sig_val = last["macd_signal"]
        hist_val = last["macd_hist"]
        cross = "BULLISH" if macd_val > sig_val else "BEARISH"
        print(f"  MACD:        {macd_val:.4f}  Signal: {sig_val:.4f}  Hist: {hist_val:.4f}  ({cross})")

    print(f"{'=' * 60}\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TD9 Sequential Indicator (Yata-style)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python td9.py AAPL                     # Daily chart
  python td9.py GME -p 1h -n 300        # 1-hour, 300 bars
  python td9.py SPY -p 1wk              # Weekly
  python td9.py NXPI --mode aggressive   # Aggressive countdown
  python td9.py BABA --show 1to9         # Show all setup counts
  python td9.py GME --no-countdown       # Setup only
  python td9.py SPY --stealth            # Enable stealth 9
  python td9.py GME --td                 # Just print the TD number
        """,
    )
    parser.add_argument("ticker", help="Stock ticker symbol (e.g., AAPL, GME, SPY)")
    parser.add_argument("-p", "--period", default="1d",
                        choices=list(PERIOD_MAP.keys()),
                        help="Timeframe (default: 1d)")
    parser.add_argument("-n", "--bars", type=int, default=200,
                        help="Number of bars to display (default: 200)")
    parser.add_argument("--mode", default="standard",
                        choices=["standard", "aggressive"],
                        help="Countdown mode (default: standard)")
    parser.add_argument("--show", default="6to9",
                        choices=["1to9", "6to9", "789", "89", "only9", "none"],
                        help="Which setup counts to show (default: 6to9)")
    parser.add_argument("--no-countdown", action="store_true",
                        help="Hide countdown (1-13) overlay")
    parser.add_argument("--no-sr", action="store_true",
                        help="Hide support/resistance levels")
    parser.add_argument("--stealth", action="store_true",
                        help="Show stealth 9 signals")
    parser.add_argument("--no-rsi", action="store_true",
                        help="Hide RSI panel")
    parser.add_argument("--no-macd", action="store_true",
                        help="Hide MACD panel")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file path (default: td9_TICKER_PERIOD.png)")
    parser.add_argument("--no-chart", action="store_true",
                        help="Text summary only, no chart")
    parser.add_argument("--td", action="store_true",
                        help="Print only the current TD setup number and exit")

    args = parser.parse_args()

    # Fetch data
    df = fetch_data(args.ticker, args.period, args.bars, quiet=args.td)

    # Compute indicators
    df = compute_all(df)

    # Trim to requested bar count
    df = df.tail(args.bars)

    # --td: just print the number and exit
    if args.td:
        last = df.iloc[-1]
        bs = int(last["buy_setup"])
        ss = int(last["sell_setup"])
        if bs > 0:
            print(bs)
        elif ss > 0:
            print(-ss)
        else:
            print(0)
        return

    # Print summary
    print_summary(df, args.ticker, args.mode)

    # Plot chart
    if not args.no_chart:
        out = plot_chart(
            df, args.ticker, args.period,
            show_mode=args.show,
            mode=args.mode,
            show_countdown=not args.no_countdown,
            show_sr=not args.no_sr,
            show_stealth=args.stealth,
            show_rsi=not args.no_rsi,
            show_macd=not args.no_macd,
            output_file=args.output,
        )
        print(f"Done. Chart saved to {out}")
    else:
        print("Done (no chart).")


if __name__ == "__main__":
    main()
