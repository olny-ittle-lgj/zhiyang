import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { portalMode } from './api'
import './styles.css'
import './light-theme.css'
import './url-capture.css'
import './image-capture.css'
import './video-capture.css'
import './manual-entry.css'
import './evolution-workflow.css'
import './games-workflow.css'
import './retro-theme.css'
import './tech-redesign.css'

const routes = [
  { path: '/', component: () => import('./pages/LandingPage.vue'), meta: { public: true } },
  { path: '/login', component: () => import('./pages/LoginPage.vue'), meta: { public: true } },
  { path: '/login/account', component: () => import('./pages/AccountAuthPage.vue'), meta: { public: true } },
  { path: '/login/phone', component: () => import('./pages/PhoneAuthPage.vue'), meta: { public: true } },
  { path: '/dashboard', component: () => import('./pages/DashboardPage.vue') },
  { path: '/my-teams', component: () => import('./pages/PersonalTeamsPage.vue') },
  { path: '/currency', component: () => import('./pages/CurrencyPage.vue') },
  { path: '/materials', component: () => import('./pages/MaterialsPage.vue') },
  { path: '/achievements', component: () => import('./pages/AchievementsPage.vue') },
  { path: '/favorites', component: () => import('./pages/FavoritesPage.vue') },
  { path: '/evolution', component: () => import('./pages/EvolutionPage.vue') },
  { path: '/teams', component: () => import('./pages/TeamsPage.vue'), meta: { portal: 'team' } },
  { path: '/games', component: () => import('./pages/GamesPage.vue') },
  { path: '/graph', component: () => import('./pages/GraphPage.vue') },
  { path: '/customer-service', component: () => import('./pages/CustomerServicePage.vue') },
  { path: '/profile', component: () => import('./pages/ProfilePage.vue') },
  { path: '/settings', component: () => import('./pages/SettingsPage.vue') },
  { path: '/share/team/:id', component: () => import('./pages/SharePage.vue'), meta: { public: true, shareType: 'team' } },
  { path: '/share/:id', component: () => import('./pages/SharePage.vue'), meta: { public: true } },
]

const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })
router.beforeEach((to) => {
  if (!to.meta.public && !localStorage.getItem('zhiyan_token')) return '/login'
  if (to.meta.portal === 'team' && portalMode() !== 'team') return '/dashboard'
  if (!to.meta.public && to.meta.portal !== 'team' && portalMode() === 'team') return '/teams'
})

createApp(App).use(router).mount('#app')
