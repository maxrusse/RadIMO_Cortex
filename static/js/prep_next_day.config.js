// Configuration parsed from JSON block to avoid Jinja/JS syntax confusion
const configElement = document.getElementById('page-config');
let CONFIG = {};

if (configElement && configElement.textContent) {
  try {
    CONFIG = JSON.parse(configElement.textContent);
  } catch (error) {
    console.error('Failed to parse page configuration JSON:', error);
  }
} else {
  console.warn('Page configuration element #page-config not found.');
}

const SKILLS = Array.isArray(CONFIG.skills) ? CONFIG.skills : [];
const MODALITIES = CONFIG.modalities || {};
const MODALITY_SETTINGS = CONFIG.modality_settings || {};
const SKILL_SETTINGS = CONFIG.skill_settings || {};
const WORKER_SKILLS = CONFIG.worker_skills || {};
const WORKER_NAMES = CONFIG.worker_names || {};
const TASK_ROLES = Array.isArray(CONFIG.task_roles) ? CONFIG.task_roles : [];
const SKILL_VALUE_COLORS = CONFIG.skill_value_colors || {};
const UI_COLORS = CONFIG.ui_colors || {};
const QUICK_BREAK = CONFIG.quick_break || { duration_minutes: 30, gap_type: 'Break', mode: 'split_shift' };

// Generate dynamic CSS for modality and skill colors from config
(function () {
  const style = document.createElement('style');
  let css = '';
  // Modality colors
  for (const [mod, settings] of Object.entries(MODALITY_SETTINGS)) {
    const navColor = settings.nav_color || '#6c757d';
    const bgColor = settings.background_color || '#f8f9fa';
    css += `.badge-${mod} { background: ${navColor}; color: white; }\n`;
    css += `.modality-border-${mod} { border-color: ${navColor}; }\n`;
    css += `.modality-bg-${mod} { background: ${bgColor}; }\n`;
  }
  // Skill colors
  for (const [skill, settings] of Object.entries(SKILL_SETTINGS)) {
    const btnColor = settings.button_color || '#6c757d';
    const textColor = settings.text_color || '#ffffff';
    const rawSlug = settings.slug || skill.toLowerCase();
    const slug = rawSlug.replace(/[^a-z0-9-]/g, '-');
    css += `.skill-header-${slug} { background: ${btnColor}; color: ${textColor}; }\n`;
    css += `.skill-btn-${slug} { background: ${btnColor}; color: ${textColor}; border: none; }\n`;
  }
  // Skill VALUE colors for text display
  const activeColor = SKILL_VALUE_COLORS.active?.color || '#28a745';
  const weightedColor = SKILL_VALUE_COLORS.weighted?.color || '#17a2b8';
  const passiveColor = SKILL_VALUE_COLORS.passive?.color || '#999';
  const excludedColor = SKILL_VALUE_COLORS.excluded?.color || '#999';
  css += `.skill-val-1 { color: ${activeColor}; font-weight: 700; }\n`;
  css += `.skill-val-0 { color: ${passiveColor}; font-weight: 400; }\n`;
  css += `.skill-val--1 { color: ${excludedColor}; font-weight: 400; }\n`;
  css += `.skill-val-w { color: ${weightedColor}; font-weight: 700; }\n`;
  // Compact border cues for edit controls: -1 red, 0 orange, w yellow, 1 green
  css += `.skill-border--1 { border-color: #c43d2c !important; box-shadow: inset 0 0 0 1px #c43d2c; }\n`;
  css += `.skill-border-0 { border-color: #d97a1f !important; box-shadow: inset 0 0 0 1px #d97a1f; }\n`;
  css += `.skill-border-w { border-color: #c8a11a !important; box-shadow: inset 0 0 0 1px #c8a11a; }\n`;
  css += `.skill-border-1 { border-color: #2f9b57 !important; box-shadow: inset 0 0 0 1px #2f9b57; }\n`;
  css += `.modifier-high { background: ${weightedColor}; color: white; }\n`;
  css += `.agg-has-weighted { color: ${weightedColor}; font-weight: bold; }\n`;
  // UI theme colors
  const todayColor = UI_COLORS.today_tab || '#28a745';
  const tomorrowColor = UI_COLORS.tomorrow_tab || '#ffc107';
  const successColor = UI_COLORS.success || '#28a745';
  const errorColor = UI_COLORS.error || '#dc3545';
  css += `.tab-btn.active-today { background: ${todayColor}; color: white; }\n`;
  css += `.today-banner { background: ${todayColor}15; border: 2px solid ${todayColor}; }\n`;
  css += `.today-banner h2, .today-banner p { color: ${todayColor}; }\n`;
  css += `.tab-btn.active-tomorrow { background: ${tomorrowColor}; color: #333; }\n`;
  css += `.tomorrow-banner { background: ${tomorrowColor}30; border: 2px solid ${tomorrowColor}; }\n`;
  css += `.tomorrow-banner h2, .tomorrow-banner p { color: #856404; }\n`;
  css += `.btn-success { background: ${successColor}; color: white; }\n`;
  css += `.btn-danger { background: ${errorColor}; color: white; }\n`;
  style.textContent = css;
  document.head.appendChild(style);
})();
