import { useState, useEffect } from 'react';

/**
 * Generic fetch hook.  Returns { data, loading, error }.
 * Re-fetches whenever `url` changes.
 * Cancels the request if the component unmounts before the response arrives.
 */
export default function useFetch(url) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    setData(null);

    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(json => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [url]);

  return { data, loading, error };
}
