# 动画系统使用指南 / Animation System Guide

## 概述 / Overview

统一的动画配置系统，解决动画冲突和不一致问题。

## 核心组件 / Core Components

### 1. AnimationConfig - 动画配置

```javascript
// 时长配置
AnimationConfig.duration.instant  // 150ms - 即时
AnimationConfig.duration.fast     // 300ms - 快速
AnimationConfig.duration.normal   // 500ms - 正常
AnimationConfig.duration.slow     // 800ms - 慢速

// 缓动函数
AnimationConfig.easing.smooth     // easeOutQuad - 平滑
AnimationConfig.easing.spring     // spring - 弹性
AnimationConfig.easing.bounce     // easeOutBounce - 弹跳

// 延迟
AnimationConfig.delay.short       // 100ms
AnimationConfig.delay.medium      // 300ms
AnimationConfig.delay.long        // 600ms
```

### 2. AnimationManager - 动画管理器

```javascript
const animMgr = window.animationManager;

// 播放预设动画
await animMgr.playPreset('my-animation', element, 'fadeIn');

// 播放自定义动画
await animMgr.play('my-animation', element, {
    opacity: [0, 1],
    translateY: [20, 0],
    duration: 500,
    easing: 'easeOutQuad'
});

// 场景过渡（防止冲突）
await animMgr.sceneTransition(async () => {
    await animMgr.playPreset('loader', loader, 'fadeOut');
    await initMainPage();
});

// 顺序播放
await animMgr.sequence([
    { id: 'anim1', targets: el1, preset: 'fadeIn' },
    { id: 'anim2', targets: el2, preset: 'slideInUp' }
]);

// 并行播放
await animMgr.parallel([
    animMgr.playPreset('anim1', el1, 'fadeIn'),
    animMgr.playPreset('anim2', el2, 'fadeIn')
]);

// 错开播放
await animMgr.stagger('cards', document.querySelectorAll('.card'), {
    opacity: [0, 1],
    translateY: [20, 0],
    duration: 500
}, 100); // 每个元素延迟100ms
```

## 预设动画 / Animation Presets

### fadeIn / fadeOut
淡入淡出效果

```javascript
animMgr.playPreset('id', element, 'fadeIn');
animMgr.playPreset('id', element, 'fadeOut');
```

### slideInUp / slideOutUp
从下方滑入/向上滑出

```javascript
animMgr.playPreset('id', element, 'slideInUp');
```

### scaleIn
缩放弹入

```javascript
animMgr.playPreset('id', element, 'scaleIn');
```

### messageEnter
消息入场动画（组合效果）

```javascript
animMgr.playPreset('id', messageElement, 'messageEnter');
```

### agentHighlight
Agent卡片高亮

```javascript
animMgr.playPreset('id', agentCard, 'agentHighlight');
```

### buttonClick
按钮点击反馈

```javascript
animMgr.playPreset('id', button, 'buttonClick');
```

## 最佳实践 / Best Practices

### 1. 使用场景过渡避免冲突

```javascript
// ❌ 错误：可能导致冲突
async function switchScene() {
    await fadeOutLoader();
    await fadeInMainPage(); // 可能与loader动画冲突
}

// ✅ 正确：使用场景过渡
async function switchScene() {
    await animMgr.sceneTransition(async () => {
        await animMgr.playPreset('loader', loader, 'fadeOut');
        await animMgr.playPreset('main', mainPage, 'fadeIn');
    });
}
```

### 2. 统一使用预设动画

```javascript
// ❌ 错误：每次都写不同的参数
anime({ targets: el, opacity: [0, 1], duration: 300 });
anime({ targets: el2, opacity: [0, 1], duration: 500 }); // 不一致！

// ✅ 正确：使用预设
animMgr.playPreset('id1', el, 'fadeIn');
animMgr.playPreset('id2', el2, 'fadeIn'); // 一致的体验
```

### 3. 给动画命名

```javascript
// ❌ 错误：无法追踪和取消
animMgr.play('animation', element, {...});

// ✅ 正确：使用有意义的ID
animMgr.play('message-123-enter', messageEl, {...});
animMgr.play('agent-A-highlight', agentCard, {...});
```

### 4. 使用顺序/并行控制流程

```javascript
// 页面加载动画
async function initPage() {
    // 先播放header
    await animMgr.sequence([
        { id: 'title', targets: '.title', preset: 'slideInUp' },
        { id: 'subtitle', targets: '.subtitle', preset: 'slideInUp' }
    ]);
    
    // 再并行播放其他元素
    await animMgr.parallel([
        animMgr.stagger('cards', '.card', {...}, 100),
        animMgr.playPreset('welcome', '.welcome', 'fadeIn')
    ]);
}
```

## 迁移指南 / Migration Guide

### 旧代码
```javascript
anime({
    targets: messageDiv,
    opacity: [0, 1],
    translateY: [20, 0],
    scale: [0.95, 1],
    duration: 600,
    easing: 'spring(1, 80, 10, 0)'
});
```

### 新代码
```javascript
animMgr.playPreset('message-enter', messageDiv, 'messageEnter');
```

## 调试 / Debugging

```javascript
// 查看当前活动的动画
console.log(animMgr.activeAnimations);

// 取消特定动画
animMgr.cancel('animation-id');

// 取消所有动画
animMgr.cancelAll();

// 检查是否在场景过渡中
console.log(animMgr.isTransitioning);
```
