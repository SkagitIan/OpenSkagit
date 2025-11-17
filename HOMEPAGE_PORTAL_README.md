# OpenSkagit.com Portal Homepage

## Overview

The new OpenSkagit.com homepage is a chatbot-first AI data portal designed to make Skagit County information accessible to citizens through natural language interaction.

## Design Philosophy

### Chatbot-First Approach
- The AI chatbot is the primary interaction method, positioned prominently in the center
- Replaces traditional navigation with intelligent guidance
- Users can ask questions in natural language to find what they need
- Tool cards below provide visual quick access for browsers

### Color Palette - Pacific Northwest Inspired

The design uses warm, earthy tones inspired by the Pacific Northwest:

- **Sage Green** (#7A9D7A) - Primary brand color, calming and natural
- **Teal** (#5B9A99) - Accent color for AI elements and interactions
- **Terracotta** (#C97C63) - Warm accent (reserved for future use)
- **Warm Gray** (#8B8680) - Secondary text and subtle elements
- **Light Gray** (#E8E6E3) - Borders and dividers
- **Off White** (#F7F6F4) - Page background
- **Charcoal** (#3C3C3C) - Primary text

These colors create a civic-minded, approachable feel that avoids corporate blue tones.

## Features

### Hero Section
- Clean, centered title: "Discover Skagit County Data"
- Subtitle explaining the portal's purpose in plain language
- Welcoming tone that invites exploration

### Chatbot Interface
- Large, prominent textarea for natural language queries
- AI-powered badge to highlight intelligent features
- Example prompts to guide first-time users
- Expandable message history that appears when conversation starts
- Real-time loading indicator
- HTMX-powered for smooth interactions without page refreshes

### Tool Cards Grid
1. **Property Tax Appeal Helper** (Active)
   - Links to `/appeal/`
   - Green "Available Now" badge
   - Brief description of functionality

2. **Budget Insights** (Coming Soon)
   - Placeholder for future budget analysis tool
   - Gray "Coming Soon" badge
   - Non-clickable state

3. **Job Outlook** (Coming Soon)
   - Placeholder for employment data analysis
   - Gray "Coming Soon" badge
   - Non-clickable state

4. **Market Analysis** (Coming Soon)
5. **Neighborhood Reports** (Coming Soon)
6. **Custom Reports** (Coming Soon)

### Responsive Design
- Mobile-first approach
- Single column on mobile, 2 columns on tablet, 3 columns on desktop
- Sticky header for easy navigation
- Touch-friendly buttons and inputs
- Optimized for all viewport sizes

## Technical Implementation

### Files Created
1. `openskagit/templates/openskagit/home_portal.html` - New homepage template
2. `openskagit/templates/partials/message_portal.html` - Chat message partial for portal design

### Files Modified
1. `openskagit/views.py` - Updated `home()` view to render new template
   - Line 1233: Changed template from `home.html` to `home_portal.html`
   - Lines 1337-1346: Updated chat view to use `message_portal.html` partial

### Integration Points
- Uses existing HTMX chat functionality
- Maintains session-based conversation management
- Compatible with existing RAG/pgvector backend
- No database changes required

### Dependencies
- HTMX 1.9.10 (loaded from CDN)
- Alpine.js 3.13.8 (loaded from CDN)
- Django templating engine
- Existing chat backend in `openskagit.llm`

## User Experience Flow

1. **Landing** - User arrives at OpenSkagit.com homepage
2. **Discovery** - Reads hero title and subtitle, sees tool cards below
3. **Interaction Choice**:
   - **Option A**: User types question into chatbot
     - System processes query through RAG pipeline
     - AI provides answer with sources
     - User can continue conversation
     - Chatbot may direct user to specific tools

   - **Option B**: User clicks on active tool card
     - Navigates directly to tool (e.g., Property Tax Appeal Helper)
     - Can return to homepage anytime

4. **Example Prompts** - Pre-filled suggestions help guide users:
   - "Find my property tax assessment"
   - "Show me recent home sales in my area"
   - "Help me understand my property value"

## Accessibility Features
- Semantic HTML structure
- Proper heading hierarchy
- ARIA labels for interactive elements
- Keyboard navigation support
- Focus visible states
- Screen reader friendly
- High contrast text/background ratios

## Browser Support
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements

### Near Term
- Add more tool cards as features are built
- Implement chatbot routing to automatically suggest tools
- Add analytics to track popular queries
- Create onboarding tour for first-time visitors

### Long Term
- Dark mode toggle
- Personalization based on user location/preferences
- Save conversation history (with user accounts)
- Share conversation links
- Export chat transcripts
- Multi-language support

## Customization

### Changing Colors
Update CSS custom properties in `home_portal.html`:
```css
:root {
  --os-sage: #7A9D7A;        /* Primary brand color */
  --os-teal: #5B9A99;        /* Accent color */
  --os-warm-gray: #8B8680;   /* Secondary text */
  /* ... etc */
}
```

### Adding New Tools
Add a new tool card in the `tools-grid` section:
```html
<a href="/your-tool/" class="tool-card active">
  <div class="tool-icon">📊</div>
  <h3 class="tool-title">Your Tool Name</h3>
  <p class="tool-description">Brief description...</p>
  <span class="tool-badge available">
    <svg><!-- checkmark icon --></svg>
    Available Now
  </span>
</a>
```

### Modifying Example Prompts
Update the example prompts section:
```html
<button class="example-prompt" onclick="setPrompt('Your custom prompt')">
  Your custom prompt text
</button>
```

## Testing Checklist
- [x] Homepage loads without errors
- [x] Chatbot input accepts text
- [x] Example prompts populate input field
- [x] Tool card links work correctly
- [x] Coming soon cards are non-clickable
- [x] Header sticky behavior works
- [x] Footer links are correct
- [x] Responsive on mobile devices
- [x] Responsive on tablet devices
- [x] Responsive on desktop devices
- [x] HTMX chat integration works
- [x] Message history displays correctly
- [x] Loading indicator shows during chat
- [x] Python syntax validates

## Deployment Notes

The new homepage is automatically active since the `home()` view was updated. No additional configuration needed.

To revert to the old design:
1. Change line 1233 in `openskagit/views.py` from `home_portal.html` back to `home.html`
2. Change lines 1337-1346 to use `message.html` instead of `message_portal.html`

## Support

For questions or issues:
1. Check browser console for JavaScript errors
2. Verify HTMX and Alpine.js are loading from CDN
3. Ensure Django session middleware is enabled
4. Test chat backend separately at `/chat/` endpoint

---

**Created**: November 2025
**Design System**: Pacific Northwest inspired, warm earth tones
**Status**: Production Ready
**Maintainer**: OpenSkagit Development Team
