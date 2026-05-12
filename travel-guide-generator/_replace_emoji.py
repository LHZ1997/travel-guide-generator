import re

with open('static/js/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Add getIcon function after first line
lines = content.split('\n')
geticon = """function getIcon(name, size = 20) {
  return `<svg width="${size}" height="${size}"><use href="#icon-${name}"/></svg>`;
}
"""
lines.insert(1, geticon)
content = '\n'.join(lines)

def gi(name, size=20):
    return f'<svg width="{size}" height="{size}"><use href="#icon-{name}"/></svg>'

# Build replacements carefully
repls = []

# 1. Message avatars
repls.append((
    "const avatar = role === 'user' ? '👤' : '🤖';",
    "const avatar = role === 'user' ? getIcon('user', 18) : getIcon('sparkle', 18);"
))
repls.append((
    '<div class="message-avatar">🤖</div>',
    f'<div class="message-avatar">{gi("sparkle", 18)}</div>'
))

# 2. Expert meta map
repls.append(("icon: '🏔️'", "icon: 'mountain'"))
repls.append(("icon: '🏨'", "icon: 'building'"))
repls.append(("icon: '🍜'", "icon: 'food'"))
repls.append(("icon: '🚗'", "icon: 'car'"))

# 3. Empty state
repls.append((
    '<div class="empty-icon">🗺️</div>',
    f'<div class="empty-icon">{gi("map", 64)}</div>'
))

# 4. Toast icons
repls.append((
    "const icons = { success: '✓', error: '✕', info: 'ℹ' };",
    "const icons = { success: getIcon('checkmark', 16), error: getIcon('xmark', 16), info: getIcon('info', 16) };"
))

# 5. Options card
repls.append((
    '<span class="options-header-icon">💡</span>',
    f'<span class="options-header-icon">{gi("lightbulb", 20)}</span>'
))

# 6. Requirements card
repls.append((
    '<span class="req-card-icon">📋</span>',
    f'<span class="req-card-icon">{gi("duplicate", 20)}</span>'
))
repls.append((
    "const statusIcon = isRequired && !hasVal ? '⚠️' : (hasVal ? '✅' : '—');",
    "const statusIcon = isRequired && !hasVal ? getIcon('warning', 14) : (hasVal ? getIcon('checkmark', 14) : '—');"
))
repls.append((
    '<div class="req-warning">⚠️ 以下必需信息尚未确认',
    f'<div class="req-warning">{gi("warning", 14)} 以下必需信息尚未确认'
))
repls.append(("✏️ 修改需求", f'{gi("pencil", 14)} 修改需求'))
repls.append(("✅ 确认，开始生成攻略", f'{gi("checkmark", 14)} 确认，开始生成攻略'))
repls.append(("⚠️ 请先补全必需信息", f'{gi("warning", 14)} 请先补全必需信息'))

# 7. Checker result
repls.append((
    '<div class="message-avatar">🔍</div>',
    f'<div class="message-avatar">{gi("search", 18)}</div>'
))
repls.append((
    "${hasCritical ? '⚠️ 发现需要关注的问题' : '✅ 攻略质量检查通过'}",
    "${hasCritical ? getIcon('warning', 14) + ' 发现需要关注的问题' : getIcon('checkmark', 14) + ' 攻略质量检查通过'}"
))

# 8. Budget warning
repls.append((
    '<div class="message-avatar">💰</div>',
    f'<div class="message-avatar">{gi("currency", 18)}</div>'
))
repls.append((
    '<span>📊 预算预估分析</span>',
    f'<span>{gi("chart", 14)} 预算预估分析</span>'
))
repls.append((
    'warnings.map(w => `<div class="budget-warning-item">⚠️ ${w}</div>`)',
    'warnings.map(w => `<div class="budget-warning-item">${getIcon(\'warning\', 14)} ${w}</div>`)'
))

# 9. EXPERT_META (different keys from expertMetaMap)
repls.append(("icon: '🎡'", "icon: 'mountain'"))

# 10. Exec logs
repls.append((
    '<div class="log-detail-label orchestrator-label">🤖 ${escapeHtml(orchestratorLog.agent_name)} (编排器)</div>',
    f'<div class="log-detail-label orchestrator-label">{gi("sparkle", 14)} ${{escapeHtml(orchestratorLog.agent_name)}} (编排器)</div>'
))
repls.append((
    '<div class="log-detail-label expert-label">🔧 ${escapeHtml(expert.agent_name)} (专家)</div>',
    f'<div class="log-detail-label expert-label">{gi("gear", 14)} ${{escapeHtml(expert.agent_name)}} (专家)</div>'
))
repls.append((
    '<div class="log-io-label error">❌ 错误</div>',
    f'<div class="log-io-label error">{gi("xmark", 14)} 错误</div>'
))

# 11. Multi choice
repls.append((
    "if (check) check.textContent = isSelected ? '☑' : '☐';",
    "if (check) check.innerHTML = isSelected ? getIcon('checkmark', 10) : '';"
))

# 12. Agent panel status
repls.append(("statusEl.textContent = '🔄';", "statusEl.innerHTML = getIcon('refresh', 14);"))
repls.append(("statusEl.textContent = '✅';", "statusEl.innerHTML = getIcon('checkmark', 14);"))
repls.append(("statusEl.textContent = '❌';", "statusEl.innerHTML = getIcon('xmark', 14);"))

# 13. Panel summary
repls.append((
    "if (done === total) summary.textContent = '全部完成 ✅';",
    "if (done === total) summary.innerHTML = '全部完成 ' + getIcon('checkmark', 14);"
))

for old, new in repls:
    if old in content:
        content = content.replace(old, new)
        print(f"OK: {old[:50]}...")
    else:
        print(f"MISS: {old[:70]}...")

with open('static/js/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nDone!")
