import '../../styles/setup.css';

import { createRoot } from 'react-dom/client';

import { SetupApp } from './SetupApp';

const container = document.getElementById('app');
if (!container) {
  throw new Error('Missing #app container');
}

createRoot(container).render(<SetupApp />);
