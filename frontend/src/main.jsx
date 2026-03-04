import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

// Keep the imported UI font setup unchanged.
const link = document.createElement('link');
link.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap';
link.rel = 'stylesheet';
document.head.appendChild(link);

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
