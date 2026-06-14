import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-chatbot',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="chatbot-container">
      <div class="chat-header">
        <h3 class="chat-title">Data Agent</h3>
        <span class="chat-subtitle">Ask questions, powered by Groq & Superset</span>
      </div>
      <div class="chat-history">
        <div *ngFor="let msg of messages" class="chat-message" [ngClass]="msg.sender">
          <div class="msg-bubble">
            <span *ngIf="msg.text">{{ msg.text }}</span>
            <div *ngIf="msg.data" class="data-block">
              <pre>{{ msg.data | json }}</pre>
            </div>
          </div>
        </div>
      </div>
      <div class="chat-input-area">
        <input 
          [(ngModel)]="currentInput" 
          (keyup.enter)="sendMessage()" 
          placeholder="Ask a question about the data..." 
          class="chat-input" 
        />
        <button (click)="sendMessage()" class="chat-send-btn">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
      </div>
    </div>
  `
})
export class ChatbotComponent {
  @Input() role = '';
  @Input() username = '';

  messages: {sender: 'user' | 'agent', text?: string, data?: any}[] = [];
  currentInput = '';

  constructor(private apiService: ApiService) {
    this.messages.push({ sender: 'agent', text: 'Hello! I am your AI Data Agent. Ask me anything about the stock market data.' });
  }

  sendMessage() {
    if (!this.currentInput.trim()) return;

    const userMessage = this.currentInput;
    this.messages.push({ sender: 'user', text: userMessage });
    this.currentInput = '';

    this.messages.push({ sender: 'agent', text: 'Analyzing data...' });

    this.apiService.sendChatQuery(userMessage, this.username, this.role).subscribe({
      next: (res) => {
        this.messages.pop();
        this.messages.push({ sender: 'agent', text: res.responseMessage, data: res.data });
      },
      error: (err) => {
        this.messages.pop();
        this.messages.push({ sender: 'agent', text: 'Error fetching data. Ensure the backend is running.' });
        console.error(err);
      }
    });
  }
}
