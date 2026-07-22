import '../../styles/chat.css';

import { createRoot } from 'react-dom/client';

import { ChatApp } from './ChatApp';

const container = document.getElementById('app');
if (!container) {
  throw new Error('Missing #app container');
}

createRoot(container).render(<ChatApp />);
