import { test, expect } from '@playwright/test';

test('create chart via chatbot and verify superset iframe', async ({ page }) => {
  // 1. Go to application
  await page.goto('/');

  // 2. Login
  await page.fill('input[type="text"]', 'investor_a');
  await page.fill('input[type="password"]', 'password123');
  await page.click('button:has-text("Authenticate")');

  // 3. Wait for dashboard to load
  await page.waitForURL('/dashboard', { timeout: 10000 });
  await page.waitForSelector('app-dashboard');

  // 4. Find chat input and send message
  const chatInput = page.locator('input[placeholder="Execute data query..."]');
  await chatInput.fill('Giúp tôi tạo 1 chart mới liên quan về Price và đưa vào dashboard Automated Market Overview');
  await page.click('button:has-text("Execute")');

  // 5. Wait for Chatbot Response (It should take ~15-30s depending on LLM)
  // We wait for the AI message that starts with 'Mình đã tạo' or just any message after ours.
  // Better: Wait for loading spinner to disappear
  await page.waitForSelector('.chat-loading', { state: 'detached', timeout: 60000 });

  // Ensure iframe src has updated to a dashboard or explore view
  const iframe = page.locator('iframe');
  await expect(iframe).toHaveAttribute('src', /explore|dashboard/, { timeout: 15000 });

  // 6. Inspect the iframe for Superset Rendering Errors
  const frameLocator = page.frameLocator('iframe');
  
  // Wait a bit for Superset to load its internal charts
  await page.waitForTimeout(5000);

  // Assert that no "Error" or "An error occurred" text exists in the Superset DOM.
  const errorText = frameLocator.locator('text="An error occurred"');
  const count = await errorText.count();
  
  if (count > 0) {
      console.log('Found an error inside Superset!');
  }
  
  expect(count).toBe(0);
});

test('chatbot answers data queries without API errors', async ({ page }) => {
  // 1. Go to application
  await page.goto('/');

  // 2. Login
  await page.fill('input[type="text"]', 'investor_a');
  await page.fill('input[type="password"]', 'password123');
  await page.click('button:has-text("Authenticate")');

  // 3. Wait for dashboard to load
  await page.waitForURL('/dashboard', { timeout: 10000 });
  await page.waitForSelector('app-dashboard');

  // 4. Send a data query message
  const chatInput = page.locator('input[placeholder="Execute data query..."]');
  await chatInput.fill('Có bao nhiêu mã cổ phiếu tất cả?');
  await page.click('button:has-text("Execute")');

  // 5. Wait for Chatbot Response
  await page.waitForSelector('.chat-loading', { state: 'detached', timeout: 60000 });

  // 6. Verify the response does not contain "lỗi" (error) or "Error"
  const messages = page.locator('.chat-message.agent .msg-bubble:not(.loading)');
  const lastMessage = messages.last();
  const text = await lastMessage.innerText();
  
  expect(text.toLowerCase()).not.toContain('lỗi từ api');
  expect(text.toLowerCase()).not.toContain('error');
});
