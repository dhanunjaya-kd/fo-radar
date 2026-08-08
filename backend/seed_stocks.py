"""Seed NSE F&O stocks. Run: python manage.py shell < seed_stocks.py"""
from screener.models import Stock

NSE_FNO_STOCKS = [
    ("RELIANCE", "Reliance Industries Ltd", "Energy", 250),
    ("TCS", "Tata Consultancy Services Ltd", "IT", 175),
    ("INFY", "Infosys Ltd", "IT", 300),
    ("HDFCBANK", "HDFC Bank Ltd", "Banking", 550),
    ("ICICIBANK", "ICICI Bank Ltd", "Banking", 700),
    ("SBIN", "State Bank of India", "Banking", 1500),
    ("BAJFINANCE", "Bajaj Finance Ltd", "NBFC", 125),
    ("BHARTIARTL", "Bharti Airtel Ltd", "Telecom", 950),
    ("ITC", "ITC Ltd", "FMCG", 1600),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd", "Banking", 400),
    ("HINDUNILVR", "Hindustan Unilever Ltd", "FMCG", 300),
    ("AXISBANK", "Axis Bank Ltd", "Banking", 625),
    ("LT", "Larsen & Toubro Ltd", "Infrastructure", 300),
    ("ASIANPAINT", "Asian Paints Ltd", "FMCG", 300),
    ("MARUTI", "Maruti Suzuki India Ltd", "Auto", 100),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "Pharma", 550),
    ("TITAN", "Titan Company Ltd", "Consumer", 350),
    ("ULTRACEMCO", "UltraTech Cement Ltd", "Cement", 100),
    ("NESTLEIND", "Nestle India Ltd", "FMCG", 40),
    ("WIPRO", "Wipro Ltd", "IT", 1000),
    ("POWERGRID", "Power Grid Corporation of India Ltd", "Power", 2700),
    ("M&M", "Mahindra & Mahindra Ltd", "Auto", 700),
    ("ADANIENT", "Adani Enterprises Ltd", "Diversified", 400),
    ("ADANIPORTS", "Adani Ports and Special Economic Zone Ltd", "Logistics", 625),
    ("COALINDIA", "Coal India Ltd", "Mining", 4200),
    ("TATAMOTORS", "Tata Motors Ltd", "Auto", 1425),
    ("BAJAJFINSV", "Bajaj Finserv Ltd", "NBFC", 289),
    ("GRASIM", "Grasim Industries Ltd", "Diversified", 462),
    ("ONGC", "Oil & Natural Gas Corporation Ltd", "Energy", 4800),
    ("NTPC", "NTPC Ltd", "Power", 5700),
    ("HCLTECH", "HCL Technologies Ltd", "IT", 350),
    ("JSWSTEEL", "JSW Steel Ltd", "Metals", 800),
    ("TECHM", "Tech Mahindra Ltd", "IT", 600),
    ("TATASTEEL", "Tata Steel Ltd", "Metals", 1750),
    ("INDUSINDBK", "IndusInd Bank Ltd", "Banking", 475),
    ("HDFCLIFE", "HDFC Life Insurance Company Ltd", "Insurance", 1100),
    ("SBILIFE", "SBI Life Insurance Company Ltd", "Insurance", 750),
    ("DRREDDY", "Dr. Reddy's Laboratories Ltd", "Pharma", 125),
    ("EICHERMOT", "Eicher Motors Ltd", "Auto", 70),
    ("BRITANNIA", "Britannia Industries Ltd", "FMCG", 200),
    ("CIPLA", "Cipla Ltd", "Pharma", 650),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise Ltd", "Healthcare", 125),
    ("UPL", "UPL Ltd", "Chemicals", 1300),
    ("HEROMOTOCO", "Hero MotoCorp Ltd", "Auto", 300),
    ("BAJAJ-AUTO", "Bajaj Auto Ltd", "Auto", 250),
    ("SHREECEM", "Shree Cement Ltd", "Cement", 25),
    ("DIVISLAB", "Divi's Laboratories Ltd", "Pharma", 150),
    ("TATACONSUM", "Tata Consumer Products Ltd", "FMCG", 900),
    ("DLF", "DLF Ltd", "Real Estate", 1650),
    ("PIDILITIND", "Pidilite Industries Ltd", "Chemicals", 250),
]

for symbol, name, sector, lot in NSE_FNO_STOCKS:
    Stock.objects.get_or_create(
        symbol=symbol,
        defaults={"name": name, "sector": sector, "lot_size": lot, "is_fno": True}
    )

print(f"Seeded {len(NSE_FNO_STOCKS)} F&O stocks.")
