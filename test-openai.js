#!/usr/bin/env node
const apiKey = process.env.OPENAI_API_KEY;
if(!apiKey){
  console.error('Missing OPENAI_API_KEY');
  process.exit(1);
}
fetch('https://api.openai.com/v1/models', {
  headers: {
    'Authorization': `Bearer ${apiKey}`
  }
})
  .then(r => r.json())
  .then(d => {
    const count = Array.isArray(d.data) ? d.data.length : 0;
    console.log('Model count:', count);
  })
  .catch(e => {
    console.error('Error talking to OpenAI:', e);
    process.exit(1);
  });
