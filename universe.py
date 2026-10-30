"""Symbol lists for each market (Yahoo Finance symbols).

Edit freely. NSE stocks end in .NS, BSE stocks in .BO.
For indices, each entry lists several Yahoo names; the app uses the first one
that returns data, because Yahoo is not consistent with NSE index names.
"""

# (name, kind, [Yahoo candidates in order of preference])
INDEX_SPECS = [
    # Broad market
    ("Nifty 50", "Broad", ["^NSEI"]),
    ("Nifty Bank", "Broad", ["^NSEBANK"]),
    ("Sensex", "Broad", ["^BSESN"]),
    ("Nifty Fin Service", "Broad", ["NIFTY_FIN_SERVICE.NS", "^CNXFIN"]),
    ("Nifty Midcap Select", "Broad", ["NIFTY_MID_SELECT.NS", "^NSEMDCPSEL"]),
    ("Nifty Midcap 100", "Broad", ["NIFTY_MIDCAP_100.NS", "^CRSMID", "^NSEMDCP100"]),
    ("Nifty Next 50", "Broad", ["^NSMIDCP", "NIFTY_NEXT_50.NS"]),
    ("Nifty Midcap 50", "Broad", ["^NSEMDCP50"]),
    ("Nifty Smallcap 100", "Broad", ["^CNXSC", "NIFTY_SMLCAP_100.NS"]),
    ("Nifty 100", "Broad", ["^CNX100"]),
    ("Nifty 200", "Broad", ["^CNX200"]),
    ("Nifty 500", "Broad", ["^CRSLDX", "NIFTY_500.NS"]),
    ("India VIX", "Broad", ["^INDIAVIX"]),
    # Sectoral and thematic
    ("Nifty IT", "Sector", ["^CNXIT"]),
    ("Nifty Auto", "Sector", ["^CNXAUTO"]),
    ("Nifty Pharma", "Sector", ["^CNXPHARMA"]),
    ("Nifty Healthcare", "Sector", ["NIFTY_HEALTHCARE.NS"]),
    ("Nifty FMCG", "Sector", ["^CNXFMCG"]),
    ("Nifty Metal", "Sector", ["^CNXMETAL"]),
    ("Nifty Realty", "Sector", ["^CNXREALTY"]),
    ("Nifty Energy", "Sector", ["^CNXENERGY"]),
    ("Nifty Oil & Gas", "Sector", ["NIFTY_OIL_AND_GAS.NS", "^CNXOILGAS"]),
    ("Nifty Media", "Sector", ["^CNXMEDIA"]),
    ("Nifty PSU Bank", "Sector", ["^CNXPSUBANK"]),
    ("Nifty Private Bank", "Sector", ["NIFTY_PVT_BANK.NS", "^CNXPVTBANK"]),
    ("Nifty Financial Services", "Sector", ["NIFTY_FIN_SERVICE.NS", "^CNXFIN"]),
    ("Nifty Infrastructure", "Sector", ["^CNXINFRA"]),
    ("Nifty Consumer Durables", "Sector", ["NIFTY_CONSR_DURBL.NS"]),
    ("Nifty Consumption", "Sector", ["^CNXCONSUM", "NIFTY_INDIA_CONSUMPTION.NS"]),
    ("Nifty Commodities", "Sector", ["^CNXCMDT"]),
    ("Nifty PSE", "Sector", ["^CNXPSE"]),
    ("Nifty CPSE", "Sector", ["NIFTY_CPSE.NS"]),
    ("Nifty MNC", "Sector", ["^CNXMNC"]),
    ("Nifty Services", "Sector", ["^CNXSERVICE"]),
    ("Nifty Capital Markets", "Sector", ["NIFTY_CAPITAL_MKT.NS"]),
    ("Nifty India Defence", "Sector", ["NIFTY_IND_DEFENCE.NS"]),
    ("Nifty Chemicals", "Sector", ["NIFTY_CHEMICALS.NS"]),
]

# Dashboard tiles: (label, [Yahoo candidates])
DASHBOARD = [
    ("Nifty 50", ["^NSEI"]),
    ("Bank Nifty", ["^NSEBANK"]),
    ("Sensex", ["^BSESN"]),
    ("Nifty Midcap 100", ["NIFTY_MIDCAP_100.NS", "^CRSMID", "^NSEMDCP100"]),
    ("Fin Nifty", ["NIFTY_FIN_SERVICE.NS", "^CNXFIN"]),
    ("BTC/USD", ["BTC-USD"]),
    ("ETH/USD", ["ETH-USD"]),
    ("XAU/USD", ["XAUUSD=X", "GC=F"]),
    ("Solana", ["SOL-USD"]),
    ("US Oil (WTI)", ["CL=F"]),
]

# NSE F&O stocks with sector. The app refreshes the symbol list and lot sizes
# from NSE's contract file each day; this list is the backup when NSE is
# unreachable, and supplies the sector names.
FNO_SECTORS = {
    "Banks": "HDFCBANK ICICIBANK SBIN KOTAKBANK AXISBANK INDUSINDBK BANKBARODA PNB CANBK FEDERALBNK IDFCFIRSTB "
             "AUBANK BANDHANBNK UNIONBANK BANKINDIA INDIANB RBLBANK YESBANK CUB KARURVYSYA MAHABANK UJJIVANSFB",
    "Financial Services": "BAJFINANCE BAJAJFINSV SHRIRAMFIN CHOLAFIN MUTHOOTFIN MANAPPURAM LICHSGFIN PFC RECLTD "
                          "IRFC SBICARD HDFCAMC HDFCLIFE SBILIFE ICICIGI ICICIPRULI LICI JIOFIN ANGELONE CDSL BSE "
                          "MCX CAMS KFINTECH IREDA POONAWALLA PAYTM POLICYBZR NUVAMA 360ONE HUDCO LTF PNBHOUSING "
                          "ABCAPITAL IIFL BAJAJHLDNG ANANDRATHI ICICILIFE MFSL MOTILALOFS NAM-INDIA",
    "IT": "TCS INFY HCLTECH WIPRO TECHM LTIM PERSISTENT COFORGE MPHASIS OFSS KPITTECH TATAELXSI TATATECH CYIENT "
          "NAUKRI LTM SAGILITY",
    "Auto": "MARUTI M&M TMPV TATAMOTORS BAJAJ-AUTO EICHERMOT HEROMOTOCO TVSMOTOR ASHOKLEY BHARATFORG MOTHERSON "
            "BOSCHLTD EXIDEIND TIINDIA UNOMINDA SONACOMS ATHERENERG FORCEMOT HYUNDAI",
    "Pharma & Healthcare": "SUNPHARMA CIPLA DRREDDY DIVISLAB LUPIN AUROPHARMA ZYDUSLIFE ALKEM TORNTPHARM BIOCON "
                           "GLENMARK LAURUSLABS MANKIND APOLLOHOSP MAXHEALTH FORTIS",
    "FMCG": "HINDUNILVR ITC NESTLEIND BRITANNIA TATACONSUM DABUR MARICO GODREJCP COLPAL VBL UNITDSPR PATANJALI "
            "GODFRYPHLP RADICO",
    "Metals & Mining": "TATASTEEL JSWSTEEL HINDALCO VEDL SAIL JINDALSTEL NMDC NATIONALUM HINDZINC COALINDIA APLAPOLLO",
    "Oil, Gas & Power": "RELIANCE ONGC BPCL IOC HINDPETRO GAIL PETRONET OIL NTPC POWERGRID TATAPOWER NHPC JSWENERGY "
                        "TORNTPOWER CESC ADANIGREEN ADANIENSOL SUZLON INOXWIND IEX ADANIPOWER PREMIERENE WAAREEENER",
    "Capital Goods & Infra": "LT BEL HAL BHEL SIEMENS ABB CGPOWER CUMMINSIND POLYCAB KEI HAVELLS BDL MAZDOCK "
                             "SOLARINDS RVNL NBCC ADANIENT ADANIPORTS GMRAIRPORT CONCOR KAYNES PGEL HFCL COCHINSHIP "
                             "DATAPATTNS ENRIN GVT&D POWERINDIA SYRMA",
    "Cement & Construction": "ULTRACEMCO GRASIM SHREECEM AMBUJACEM DALBHARAT",
    "Consumer & Retail": "TITAN ASIANPAINT PIDILITIND BLUESTARCO VOLTAS DIXON AMBER KALYANKJIL TRENT DMART NYKAA "
                         "ETERNAL SWIGGY PAGEIND JUBLFOOD INDHOTEL IRCTC INDIGO DELHIVERY CROMPTON VMM",
    "Telecom": "BHARTIARTL IDEA INDUSTOWER TATACOMM",
    "Realty": "DLF GODREJPROP OBEROIRLTY LODHA PRESTIGE PHOENIXLTD",
    "Chemicals": "PIIND UPL SRF DEEPAKNTR TATACHEM COROMANDEL SUPREMEIND ASTRAL NAVINFLUOR",
}
FNO_SECTOR_OF = {s: sec for sec, names in FNO_SECTORS.items() for s in names.split()}

CRYPTO = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana", "BNB-USD": "BNB", "XRP-USD": "XRP",
    "DOGE-USD": "Dogecoin", "ADA-USD": "Cardano", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink",
    "DOT-USD": "Polkadot", "LTC-USD": "Litecoin", "TRX-USD": "TRON", "SHIB-USD": "Shiba Inu",
    "TON11419-USD": "Toncoin", "SUI20947-USD": "Sui", "NEAR-USD": "NEAR", "UNI7083-USD": "Uniswap",
    "BCH-USD": "Bitcoin Cash", "XLM-USD": "Stellar", "PEPE24478-USD": "Pepe",
}

FOREX = {
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF", "NZDUSD=X": "NZD/USD", "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY", "EURGBP=X": "EUR/GBP", "AUDJPY=X": "AUD/JPY", "EURCHF=X": "EUR/CHF",
    "USDCNY=X": "USD/CNY", "USDSGD=X": "USD/SGD", "USDHKD=X": "USD/HKD", "DX-Y.NYB": "US Dollar Index",
}

INR_CURRENCY = {
    "USDINR=X": "USD/INR", "EURINR=X": "EUR/INR", "GBPINR=X": "GBP/INR", "JPYINR=X": "JPY/INR",
    "AUDINR=X": "AUD/INR", "CADINR=X": "CAD/INR", "CHFINR=X": "CHF/INR", "SGDINR=X": "SGD/INR",
    "AEDINR=X": "AED/INR", "SARINR=X": "SAR/INR", "CNYINR=X": "CNY/INR", "HKDINR=X": "HKD/INR",
    "NZDINR=X": "NZD/INR", "THBINR=X": "THB/INR",
}

COMMODITIES = {
    "GC=F": "Gold (COMEX)", "SI=F": "Silver (COMEX)", "PL=F": "Platinum", "PA=F": "Palladium",
    "HG=F": "Copper", "CL=F": "Crude Oil WTI", "BZ=F": "Brent Crude", "NG=F": "Natural Gas",
    "RB=F": "Gasoline", "ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans", "KC=F": "Coffee",
    "SB=F": "Sugar", "CT=F": "Cotton",
}


def fno_yahoo(sym: str) -> str:
    return sym + ".NS"


def fno_names() -> dict:
    return {fno_yahoo(s): s for s in FNO_SECTOR_OF}


def index_names() -> dict:
    out = {}
    for name, _, cands in INDEX_SPECS:
        for c in cands:
            out.setdefault(c, name)
    return out


# Dhan-only instruments (nearest futures contract, rolled automatically)
MCX = {"MCX:GOLD": "Gold (MCX)", "MCX:GOLDM": "Gold Mini (MCX)", "MCX:SILVER": "Silver (MCX)",
       "MCX:SILVERM": "Silver Mini (MCX)", "MCX:CRUDEOIL": "Crude Oil (MCX)", "MCX:CRUDEOILM": "Crude Oil Mini (MCX)",
       "MCX:NATURALGAS": "Natural Gas (MCX)", "MCX:NATGASMINI": "Natural Gas Mini (MCX)", "MCX:COPPER": "Copper (MCX)",
       "MCX:ZINC": "Zinc (MCX)", "MCX:ALUMINIUM": "Aluminium (MCX)", "MCX:LEAD": "Lead (MCX)"}
CURRENCY_FUT = {"CDS:USDINR": "USD/INR Fut", "CDS:EURINR": "EUR/INR Fut", "CDS:GBPINR": "GBP/INR Fut",
                "CDS:JPYINR": "JPY/INR Fut", "CDS:EURUSD": "EUR/USD Fut", "CDS:GBPUSD": "GBP/USD Fut",
                "CDS:USDJPY": "USD/JPY Fut"}

# Underlyings with option chains on Dhan: label -> (Dhan security id, segment); stocks are added at runtime
OC_INDICES = {"NIFTY": (13, "IDX_I"), "BANKNIFTY": (25, "IDX_I"), "FINNIFTY": (27, "IDX_I"),
              "MIDCPNIFTY": (442, "IDX_I"), "SENSEX": (51, "IDX_I")}
OC_INDEX_SYMBOL = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                   "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "SENSEX": "^BSESN"}

GROUPS = {
    "F&O Stocks": fno_names(),
    "Indian Indices": {c[0]: n for n, _, c in INDEX_SPECS},
    "Crypto": CRYPTO,
    "Forex": FOREX,
    "Currency (INR)": INR_CURRENCY,
    "Commodities": COMMODITIES,
    "MCX (Dhan)": MCX,
    "Currency Futures (Dhan)": CURRENCY_FUT,
}

INR_GROUPS = {"F&O Stocks", "Indian Indices", "MCX (Dhan)"}


def index_label(symbol: str):
    """Index name for a Yahoo index symbol, or None."""
    for name, _, cands in INDEX_SPECS:
        if symbol in cands:
            return name
    return None


def all_names() -> dict:
    names = {}
    for g in GROUPS.values():
        names.update(g)
    names.update(index_names())
    names.setdefault("XAUUSD=X", "XAU/USD")
    return names


def group_of(symbol: str) -> str:
    if symbol.startswith("MCX:"):
        return "MCX (Dhan)"
    if symbol.startswith("CDS:"):
        return "Currency Futures (Dhan)"
    for gname, g in GROUPS.items():
        if symbol in g:
            return gname
    if symbol in index_names() or symbol.startswith("^") or symbol.startswith("NIFTY_"):
        return "Indian Indices"
    if symbol.endswith((".NS", ".BO")):
        return "F&O Stocks"
    if symbol.endswith("-USD"):
        return "Crypto"
    if symbol.endswith("INR=X"):
        return "Currency (INR)"
    if symbol in ("XAUUSD=X", "XAGUSD=X") or symbol.endswith("=F"):
        return "Commodities"
    if symbol.endswith("=X"):
        return "Forex"
    return "F&O Stocks"


def normalize(symbol: str) -> str:
    """Turn what a person types (reliance, btc, eurusd, gold) into a Yahoo symbol."""
    s = symbol.strip().upper().replace(" ", "")
    if not s:
        return s
    aliases = {
        "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "NIFTYBANK": "^NSEBANK",
        "SENSEX": "^BSESN", "VIX": "^INDIAVIX", "INDIAVIX": "^INDIAVIX",
        "FINNIFTY": "NIFTY_FIN_SERVICE.NS", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
        "MIDCAP": "NIFTY_MIDCAP_100.NS", "NIFTYIT": "^CNXIT",
        "GOLD": "GC=F", "XAUUSD": "GC=F", "SILVER": "SI=F", "XAGUSD": "SI=F",
        "CRUDE": "CL=F", "CRUDEOIL": "CL=F", "WTI": "CL=F", "USOIL": "CL=F", "BRENT": "BZ=F", "UKOIL": "BZ=F",
        "NATURALGAS": "NG=F", "NATGAS": "NG=F", "COPPER": "HG=F", "DXY": "DX-Y.NYB",
    }
    if s in aliases:
        return aliases[s]
    if s.startswith("^") or s.endswith((".NS", ".BO", "=X", "=F", "-USD")) or "." in s:
        return s
    crypto_bases = {k.split("-")[0] for k in CRYPTO}
    if s in crypto_bases or s.endswith("USDT"):
        return s.replace("USDT", "") + "-USD"
    ccy = {"EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY", "SGD", "INR", "AED", "CNY", "HKD", "SAR"}
    if len(s) == 6 and s[:3] in ccy and s[3:] in ccy:
        return s + "=X"
    return s + ".NS"
