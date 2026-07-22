import '../../styles/plan-view.css';

import { createRoot } from 'react-dom/client';

import { PlanViewApp } from './PlanViewApp';

const container = document.getElementById('app');
if (!container) {
  throw new Error('Missing #app container');
}

createRoot(container).render(<PlanViewApp />);
