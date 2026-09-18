"""
Sep 18/19 2026: NIFTY 500 universe for the Market Pulse breadth panel
ONLY -- deliberately separate from FNO_STOCKS (views.py), which stays
exactly as-is and continues to drive the live signal engine untouched.

Source: NSE Indices' own official NIFTY 500 constituent list (Symbol,
Series, Industry, ISIN), via its Wikipedia mirror snapshot dated
26 November 2024 -- https://en.wikipedia.org/wiki/NIFTY_500 (that page
itself flags it needs a refresh). NOT fabricated, but also NOT live:
NIFTY 500 membership is rebalanced by NSE Indices twice a year (cutoff
Jan 31 / Jul 31), so a handful of names in a real current list may
differ from this snapshot by now, mostly at the small-cap tail (the
eligibility rule is top-800 by market cap + turnover, so mega/large
caps essentially never churn out). Re-pull and regenerate this file
from NSE's live list periodically -- don't hand-edit around it.

500 rows verified (parsed + counted programmatically, not hand-typed).
Bare symbols only (e.g. "RELIANCE", not "NSE:RELIANCE-EQ") -- matches
FNO_STOCKS' own convention exactly, because _fetch_all_quotes_fyers()
(views.py) hardcodes the f"NSE:{s}-EQ" wrapping itself and expects
bare input. That hardcoding also means it unconditionally assumes EQ
series: the source list's 3 real BE-series (T2T) names -- JAIBALAJI,
LATENTVIEW, SANOFI -- get wrapped as "-EQ" anyway, wrongly, and will
just come back empty from Fyers. Left as-is rather than special-cased:
same "a symbol that fails this pass just isn't in count_with_data"
principle already used everywhere else in this pipeline, for a 3-of-
500 (0.6%) gap.

NIFTY_500_SECTOR_FALLBACK: sector labels for ONLY the ~303 of these
500 symbols NOT already covered by views.py's own SECTORS dict (the
208 F&O names keep whatever SECTORS already says for them, untouched
-- this never overrides an existing entry). Built by mapping the
source list's own "Industry" column onto this project's existing
short-label vocabulary (Auto/Finance/IT/Cement/Metals/Energy/etc)
wherever an existing label is an honest match; kept as the source's
own category name verbatim (Services/Consumer Services/Forest
Materials) where folding it into an existing label would mean
guessing a fit that isn't really there. Two judgment calls, both
anchored to a precedent already in views.py's own SECTORS dict rather
than invented fresh: "Construction" -> "Infra" (matches LT's own
existing entry) and "Diversified" -> "Conglomerate" (matches
ADANIENT's own existing entry).
"""

NIFTY_500_STOCKS = [
    "360ONE", "3MINDIA", "ABB", "ACC", "AIAENG", "APLAPOLLO", "AUBANK", "AARTIIND",
    "AAVAS", "ABBOTINDIA", "ACE", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIPOWER",
    "ATGL", "AWL", "ABCAPITAL", "ABFRL", "AEGISLOG", "AETHER", "AFFLE", "AJANTPHARM",
    "APLLTD", "ALKEM", "ALKYLAMINE", "ALLCARGO", "ALOKINDS", "ARE&M", "AMBER", "AMBUJACEM",
    "ANANDRATHI", "ANGELONE", "ANURAS", "APARINDS", "APOLLOHOSP", "APOLLOTYRE", "APTUS", "ACI",
    "ASAHIINDIA", "ASHOKLEY", "ASIANPAINT", "ASTERDM", "ASTRAZEN", "ASTRAL", "ATUL", "AUROPHARMA",
    "AVANTIFEED", "DMART", "AXISBANK", "BEML", "BLS", "BSE", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BAJAJHLDNG", "BALAMINES", "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BANKINDIA",
    "MAHABANK", "BATAINDIA", "BAYERCROP", "BERGEPAINT", "BDL", "BEL", "BHARATFORG", "BHEL",
    "BPCL", "BHARTIARTL", "BIKAJI", "BIOCON", "BIRLACORPN", "BSOFT", "BLUEDART", "BLUESTARCO",
    "BBTC", "BORORENEW", "BOSCHLTD", "BRIGADE", "BRITANNIA", "MAPMYINDIA", "CCL", "CESC",
    "CGPOWER", "CIEINDIA", "CRISIL", "CSBBANK", "CAMPUS", "CANFINHOME", "CANBK", "CAPLIPOINT",
    "CGCL", "CARBORUNIV", "CASTROLIND", "CEATLTD", "CELLO", "CENTRALBK", "CDSL", "CENTURYPLY",
    "ABREL", "CERA", "CHALET", "CHAMBLFERT", "CHEMPLASTS", "CHENNPETRO", "CHOLAHLDNG", "CHOLAFIN",
    "CIPLA", "CUB", "CLEAN", "COALINDIA", "COCHINSHIP", "COFORGE", "COLPAL", "CAMS",
    "CONCORDBIO", "CONCOR", "COROMANDEL", "CRAFTSMAN", "CREDITACC", "CROMPTON", "CUMMINSIND", "CYIENT",
    "DCMSHRIRAM", "DLF", "DOMS", "DABUR", "DALBHARAT", "DATAPATTNS", "DEEPAKFERT", "DEEPAKNTR",
    "DELHIVERY", "DEVYANI", "DIVISLAB", "DIXON", "LALPATHLAB", "DRREDDY", "EIDPARRY", "EIHOTEL",
    "EPL", "EASEMYTRIP", "EICHERMOT", "ELECON", "ELGIEQUIP", "EMAMILTD", "ENDURANCE", "ENGINERSIN",
    "EQUITASBNK", "ERIS", "ESCORTS", "EXIDEIND", "FDC", "NYKAA", "FEDERALBNK", "FACT",
    "FINEORG", "FINCABLES", "FINPIPE", "FSL", "FIVESTAR", "FORTIS", "GAIL", "GMMPFAUDLR",
    "GMRINFRASTRUCT", "GRSE", "GICRE", "GILLETTE", "GLAND", "GLAXO", "ALIVUS", "GLENMARK",
    "MEDANTA", "GPIL", "GODFRYPHLP", "GODREJCP", "GODREJIND", "GODREJPROP", "GRANULES", "GRAPHITE",
    "GRASIM", "GESHIP", "GRINDWELL", "GAEL", "FLUOROCHEM", "GUJGASLTD", "GMDCLTD", "GNFC",
    "GPPL", "GSFC", "GSPL", "HEG", "HBLENGINE", "HCLTECH", "HDFCAMC", "HDFCBANK",
    "HDFCLIFE", "HFCL", "HAPPSTMNDS", "HAPPYFORGE", "HAVELLS", "HEROMOTOCO", "HSCL", "HINDALCO",
    "HAL", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "HINDZINC", "POWERINDIA", "HOMEFIRST", "HONASA",
    "HONAUT", "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "ISEC", "IDBI", "IDFCFIRSTB",
    "IFCI", "IIFL", "IRB", "IRCON", "ITC", "ITI", "INDIACEM", "INDIAMART",
    "INDIANB", "IEX", "INDHOTEL", "IOC", "IOB", "IRCTC", "IRFC", "INDIGOPNTS",
    "IGL", "INDUSTOWER", "INDUSINDBK", "NAUKRI", "INFY", "INOXWIND", "INTELLECT", "INDIGO",
    "IPCALAB", "JBCHEPHARM", "JKCEMENT", "JBMA", "JKLAKSHMI", "JKPAPER", "JMFINANCIL", "JSWENERGY",
    "JSWINFRA", "JSWSTEEL", "JAIBALAJI", "J&KBANK", "JINDALSAW", "JSL", "JINDALSTEL", "JIOFIN",
    "JUBLFOOD", "JUBLINGREA", "JUBLPHARMA", "JWL", "JUSTDIAL", "JYOTHYLAB", "KPRMILL", "KEI",
    "KNRCON", "KPITTECH", "KRBL", "KSB", "KAJARIACER", "KPIL", "KALYANKJIL", "KANSAINER",
    "KARURVYSYA", "KAYNES", "KEC", "KFINTECH", "KOTAKBANK", "KIMS", "LTF", "LTTS",
    "LICHSGFIN", "LTIM", "LT", "LATENTVIEW", "LAURUSLABS", "LXCHEM", "LEMONTREE", "LICI",
    "LINDEINDIA", "LLOYDSME", "LUPIN", "MMTC", "MRF", "MTARTECH", "LODHA", "MGL",
    "MAHSEAMLES", "M&MFIN", "M&M", "MHRIL", "MAHLIFE", "MANAPPURAM", "MRPL", "MANKIND",
    "MARICO", "MARUTI", "MASTEK", "MFSL", "MAXHEALTH", "MAZDOCK", "MEDPLUS", "METROBRAND",
    "METROPOLIS", "MINDACORP", "MSUMI", "MOTILALOFS", "MPHASIS", "MCX", "MUTHOOTFIN", "NATCOPHARM",
    "NBCC", "NCC", "NHPC", "NLCINDIA", "NMDC", "NSLNISP", "NTPC", "NH",
    "NATIONALUM", "NAVINFLUOR", "NESTLEIND", "NETWORK18", "NAM-INDIA", "NUVAMA", "NUVOCO", "OBEROIRLTY",
    "ONGC", "OIL", "OLECTRA", "PAYTM", "OFSS", "POLICYBZR", "PCBL", "PIIND",
    "PNBHOUSING", "PNCINFRA", "PVRINOX", "PAGEIND", "PATANJALI", "PERSISTENT", "PETRONET", "PHOENIXLTD",
    "PIDILITIND", "PEL", "PPLPHARMA", "POLYMED", "POLYCAB", "POONAWALLA", "PFC", "POWERGRID",
    "PRAJIND", "PRESTIGE", "PRINCEPIPE", "PRSMJOHNSN", "PGHH", "PNB", "QUESS", "RRKABEL",
    "RBLBANK", "RECLTD", "RHIM", "RITES", "RADICO", "RVNL", "RAILTEL", "RAINBOW",
    "RAJESHEXPO", "RKFORGE", "RCF", "RATNAMANI", "RTNINDIA", "RAYMOND", "REDINGTON", "RELIANCE",
    "RBA", "ROUTE", "SBFC", "SBICARD", "SBILIFE", "SJVN", "SKFINDIA", "SRF",
    "SAFARI", "SAMMAANCAP", "MOTHERSON", "SANOFI", "SAPPHIRE", "SAREGAMA", "SCHAEFFLER", "SCHNEIDER",
    "SHREECEM", "RENUKA", "SHRIRAMFIN", "SHYAMMETL", "SIEMENS", "SIGNATURE", "SOBHA", "SOLARINDS",
    "SONACOMS", "SONATSOFTW", "STARHEALTH", "SBIN", "SAIL", "SWSOLAR", "STLTECH", "SUMICHEM",
    "SPARC", "SUNPHARMA", "SUNTV", "SUNDARMFIN", "SUNDRMFAST", "SUNTECK", "SUPREMEIND", "SUVENPHAR",
    "SUZLON", "SWANENERGY", "SYNGENE", "SYRMA", "TBOTEK", "TVSMOTOR", "TVSSCS", "TMB",
    "TANLA", "TATACHEM", "TATACOMM", "TCS", "TATACONSUM", "TATAELXSI", "TATAINVEST", "TATAMOTORS",
    "TATAPOWER", "TATASTEEL", "TATATECH", "TTML", "TECHM", "TEJASNET", "NIACL", "RAMCOCEM",
    "THERMAX", "TIMKEN", "TITAGARH", "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TRIDENT",
    "TRIVENI", "TRITURBINE", "TIINDIA", "UCOBANK", "UNOMINDA", "UPL", "UTIAMC", "UJJIVANSFB",
    "ULTRACEMCO", "UNIONBANK", "UBL", "UNITDSPR", "USHAMART", "VGUARD", "VIPIND", "VAIBHAVGBL",
    "VTL", "VARROC", "VBL", "MANYAVAR", "VEDL", "VIJAYA", "IDEA", "VOLTAS",
    "WELCORP", "WELSPUNLIV", "WESTLIFE", "WHIRLPOOL", "WIPRO", "YESBANK", "ZFCVINDIA", "ZEEL",
    "ZENSARTECH", "ETERNAL", "ZYDUSLIFE", "ECLERX",
]

NIFTY_500_SECTOR_FALLBACK = {
    "3MINDIA": "Conglomerate", "AARTIIND": "Chemicals", "AAVAS": "Finance", "ABBOTINDIA": "Healthcare",
    "ABFRL": "Consumer Services", "ABREL": "Forest Materials", "ACC": "Cement", "ACE": "Capital Goods",
    "ACI": "Chemicals", "AEGISLOG": "Energy", "AETHER": "Chemicals", "AFFLE": "IT",
    "AIAENG": "Capital Goods", "AJANTPHARM": "Healthcare", "ALIVUS": "Healthcare", "ALKYLAMINE": "Chemicals",
    "ALLCARGO": "Services", "ALOKINDS": "Textile", "ANANDRATHI": "Finance", "ANURAS": "Chemicals",
    "APARINDS": "Capital Goods", "APLLTD": "Healthcare", "APOLLOTYRE": "Auto", "APTUS": "Finance",
    "ARE&M": "Auto", "ASAHIINDIA": "Auto", "ASTERDM": "Healthcare", "ASTRAZEN": "Healthcare",
    "ATGL": "Energy", "ATUL": "Chemicals", "AVANTIFEED": "FMCG", "AWL": "FMCG",
    "BALAMINES": "Chemicals", "BALKRISIND": "Auto", "BALRAMCHIN": "FMCG", "BATAINDIA": "Consumer Durables",
    "BAYERCROP": "Chemicals", "BBTC": "FMCG", "BEML": "Capital Goods", "BERGEPAINT": "Consumer Durables",
    "BIKAJI": "FMCG", "BIRLACORPN": "Cement", "BLS": "Consumer Services", "BLUEDART": "Services",
    "BORORENEW": "Capital Goods", "BRIGADE": "Realty", "BSOFT": "IT", "CAMPUS": "Consumer Durables",
    "CANFINHOME": "Finance", "CAPLIPOINT": "Healthcare", "CARBORUNIV": "Capital Goods", "CASTROLIND": "Energy",
    "CCL": "FMCG", "CEATLTD": "Auto", "CELLO": "Consumer Durables", "CENTRALBK": "Finance",
    "CENTURYPLY": "Consumer Durables", "CERA": "Consumer Durables", "CESC": "Power", "CGCL": "Finance",
    "CHALET": "Consumer Services", "CHAMBLFERT": "Chemicals", "CHEMPLASTS": "Chemicals", "CHENNPETRO": "Energy",
    "CHOLAHLDNG": "Finance", "CIEINDIA": "Auto", "CLEAN": "Chemicals", "CONCORDBIO": "Healthcare",
    "COROMANDEL": "Chemicals", "CRAFTSMAN": "Auto", "CREDITACC": "Finance", "CRISIL": "Finance",
    "CSBBANK": "Finance", "CUB": "Finance", "CYIENT": "IT", "DATAPATTNS": "Capital Goods",
    "DCMSHRIRAM": "Conglomerate", "DEEPAKFERT": "Chemicals", "DEEPAKNTR": "Chemicals", "DEVYANI": "Consumer Services",
    "DOMS": "FMCG", "EASEMYTRIP": "Consumer Services", "ECLERX": "Services", "EIDPARRY": "Chemicals",
    "EIHOTEL": "Consumer Services", "ELECON": "Capital Goods", "ELGIEQUIP": "Capital Goods", "EMAMILTD": "FMCG",
    "ENDURANCE": "Auto", "ENGINERSIN": "Infra", "EPL": "Capital Goods", "EQUITASBNK": "Finance",
    "ERIS": "Healthcare", "ESCORTS": "Capital Goods", "EXIDEIND": "Auto", "FACT": "Chemicals",
    "FDC": "Healthcare", "FINCABLES": "Capital Goods", "FINEORG": "Chemicals", "FINPIPE": "Capital Goods",
    "FIVESTAR": "Finance", "FLUOROCHEM": "Chemicals", "FSL": "Services", "GAEL": "FMCG",
    "GESHIP": "Services", "GICRE": "Finance", "GILLETTE": "FMCG", "GLAND": "Healthcare",
    "GLAXO": "Healthcare", "GMDCLTD": "Metals", "GMMPFAUDLR": "Capital Goods", "GMRINFRASTRUCT": "Services",
    "GNFC": "Chemicals", "GODREJIND": "Conglomerate", "GPIL": "Capital Goods", "GPPL": "Services",
    "GRANULES": "Healthcare", "GRAPHITE": "Capital Goods", "GRINDWELL": "Capital Goods", "GRSE": "Capital Goods",
    "GSFC": "Chemicals", "GSPL": "Energy", "GUJGASLTD": "Energy", "HAPPSTMNDS": "IT",
    "HAPPYFORGE": "Capital Goods", "HBLENGINE": "Auto", "HEG": "Capital Goods", "HFCL": "Telecom",
    "HINDCOPPER": "Metals", "HOMEFIRST": "Finance", "HONASA": "FMCG", "HONAUT": "Capital Goods",
    "HSCL": "Chemicals", "HUDCO": "Finance", "IDBI": "Finance", "IFCI": "Finance",
    "IGL": "Energy", "IIFL": "Finance", "INDIACEM": "Cement", "INDIAMART": "Consumer Services",
    "INDIGOPNTS": "Consumer Durables", "INTELLECT": "IT", "IOB": "Finance", "IPCALAB": "Healthcare",
    "IRB": "Infra", "IRCON": "Infra", "IRCTC": "Consumer Services", "ISEC": "Finance",
    "ITI": "Telecom", "J&KBANK": "Finance", "JAIBALAJI": "Metals", "JBCHEPHARM": "Healthcare",
    "JBMA": "Auto", "JINDALSAW": "Capital Goods", "JKCEMENT": "Cement", "JKLAKSHMI": "Cement",
    "JKPAPER": "Forest Materials", "JMFINANCIL": "Finance", "JSL": "Metals", "JSWINFRA": "Services",
    "JUBLINGREA": "Chemicals", "JUBLPHARMA": "Healthcare", "JUSTDIAL": "Consumer Services", "JWL": "Capital Goods",
    "JYOTHYLAB": "FMCG", "KAJARIACER": "Consumer Durables", "KANSAINER": "Consumer Durables", "KARURVYSYA": "Finance",
    "KEC": "Infra", "KIMS": "Healthcare", "KNRCON": "Infra", "KPIL": "Infra",
    "KPRMILL": "Textile", "KRBL": "FMCG", "KSB": "Capital Goods", "LALPATHLAB": "Healthcare",
    "LATENTVIEW": "IT", "LEMONTREE": "Consumer Services", "LINDEINDIA": "Chemicals", "LLOYDSME": "Metals",
    "LTTS": "IT", "LXCHEM": "Chemicals", "M&MFIN": "Finance", "MAHABANK": "Finance",
    "MAHLIFE": "Realty", "MAHSEAMLES": "Capital Goods", "MANYAVAR": "Consumer Services", "MAPMYINDIA": "IT",
    "MASTEK": "IT", "MEDANTA": "Healthcare", "MEDPLUS": "Consumer Services", "METROBRAND": "Consumer Durables",
    "METROPOLIS": "Healthcare", "MGL": "Energy", "MHRIL": "Consumer Services", "MINDACORP": "Auto",
    "MMTC": "Services", "MRF": "Auto", "MRPL": "Energy", "MSUMI": "Auto",
    "MTARTECH": "Capital Goods", "NATCOPHARM": "Healthcare", "NAVINFLUOR": "Chemicals", "NCC": "Infra",
    "NETWORK18": "Media", "NH": "Healthcare", "NIACL": "Finance", "NLCINDIA": "Power",
    "NSLNISP": "Metals", "NUVAMA": "Finance", "NUVOCO": "Cement", "OLECTRA": "Auto",
    "PCBL": "Chemicals", "PEL": "Finance", "PGHH": "FMCG", "PNCINFRA": "Infra",
    "POLYMED": "Healthcare", "POONAWALLA": "Finance", "PPLPHARMA": "Healthcare", "PRAJIND": "Capital Goods",
    "PRINCEPIPE": "Capital Goods", "PRSMJOHNSN": "Cement", "PVRINOX": "Media", "QUESS": "Services",
    "RAILTEL": "Telecom", "RAINBOW": "Healthcare", "RAJESHEXPO": "Consumer Durables", "RAMCOCEM": "Cement",
    "RATNAMANI": "Capital Goods", "RAYMOND": "Textile", "RBA": "Consumer Services", "RCF": "Chemicals",
    "REDINGTON": "Services", "RENUKA": "FMCG", "RHIM": "Capital Goods", "RITES": "Infra",
    "RKFORGE": "Auto", "ROUTE": "Telecom", "RRKABEL": "Capital Goods", "RTNINDIA": "Consumer Services",
    "SAFARI": "Consumer Durables", "SAMMAANCAP": "Finance", "SANOFI": "Healthcare", "SAPPHIRE": "Consumer Services",
    "SAREGAMA": "Media", "SBFC": "Finance", "SCHAEFFLER": "Auto", "SCHNEIDER": "Capital Goods",
    "SHYAMMETL": "Capital Goods", "SIGNATURE": "Realty", "SJVN": "Power", "SKFINDIA": "Capital Goods",
    "SOBHA": "Realty", "SONATSOFTW": "IT", "SPARC": "Healthcare", "STARHEALTH": "Finance",
    "STLTECH": "Telecom", "SUMICHEM": "Chemicals", "SUNDARMFIN": "Finance", "SUNDRMFAST": "Auto",
    "SUNTECK": "Realty", "SUNTV": "Media", "SUVENPHAR": "Healthcare", "SWANENERGY": "Conglomerate",
    "SWSOLAR": "Infra", "SYNGENE": "Healthcare", "SYRMA": "Capital Goods", "TANLA": "IT",
    "TATACHEM": "Chemicals", "TATACOMM": "Telecom", "TATAINVEST": "Finance", "TATAMOTORS": "Auto",
    "TATATECH": "IT", "TBOTEK": "Consumer Services", "TEJASNET": "Telecom", "THERMAX": "Capital Goods",
    "TIMKEN": "Capital Goods", "TITAGARH": "Capital Goods", "TMB": "Finance", "TORNTPOWER": "Power",
    "TRIDENT": "Textile", "TRITURBINE": "Capital Goods", "TRIVENI": "FMCG", "TTML": "Telecom",
    "TVSSCS": "Services", "UBL": "FMCG", "UCOBANK": "Finance", "UJJIVANSFB": "Finance",
    "USHAMART": "Capital Goods", "UTIAMC": "Finance", "VAIBHAVGBL": "Consumer Durables", "VARROC": "Auto",
    "VGUARD": "Consumer Durables", "VIJAYA": "Healthcare", "VIPIND": "Consumer Durables", "VTL": "Textile",
    "WELCORP": "Capital Goods", "WELSPUNLIV": "Textile", "WESTLIFE": "Consumer Services", "WHIRLPOOL": "Consumer Durables",
    "ZEEL": "Media", "ZENSARTECH": "IT", "ZFCVINDIA": "Auto",
}
