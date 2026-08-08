import { useState, useEffect } from 'react';
import './MarqueeTicker.css';

const MarqueeTicker = () => {
  const [stocks, setStocks] = useState([]);

  useEffect(() => {
    fetch('http://127.0.0.1:8000/api/stocks/fo-list/')
      .then(r => r.json())
      .then(data => {
        if (data.stocks) setStocks(data.stocks);
      })
      .catch(err => console.error('Ticker fetch error:', err));
  }, []);

  const displayStocks = [...stocks, ...stocks];

  return (
    <div className="marquee-container">
      <div className="marquee-content">
        {displayStocks.map((stock, i) => (
          <span key={`${stock.symbol}-${i}`} className="ticker-item">
            <span className="ticker-symbol">{stock.symbol}</span>
            <span className="ticker-price">₹{stock.price?.toFixed(2)}</span>
            <span className={`ticker-change ${(stock.change || 0) >= 0 ? 'up' : 'down'}`}>
              {(stock.change || 0) >= 0 ? '▲' : '▼'}
              {Math.abs(stock.change || 0).toFixed(2)} 
              ({(stock.change_percent || 0).toFixed(2)}%)
            </span>
          </span>
        ))}
      </div>
    </div>
  );
};

export default MarqueeTicker;