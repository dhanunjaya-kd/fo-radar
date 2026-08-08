import { useEffect, useState } from 'react';
import { fyersSocket } from '../services/fyersSocket';

export function useFyersTick(symbol) {
  const [tick, setTick] = useState(null);

  useEffect(() => {
    if (!symbol) return;

    fyersSocket.connect();
    
    const handleTick = (data) => {
      setTick(data);
    };

    fyersSocket.onTick(symbol, handleTick);

    return () => {
      fyersSocket.offTick(symbol, handleTick);
    };
  }, [symbol]);

  return tick;
}