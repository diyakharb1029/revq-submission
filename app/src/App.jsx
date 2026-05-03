import { Routes, Route } from 'react-router-dom';
import ProductList   from './pages/ProductList';
import ProductDetail from './pages/ProductDetail';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <img src="/logo.png" alt="RevQ" className="app-logo-img" />
        <span className="app-tagline">Brand Intelligence</span>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/"            element={<ProductList />} />
          <Route path="/product/:id" element={<ProductDetail />} />
        </Routes>
      </main>
    </div>
  );
}
