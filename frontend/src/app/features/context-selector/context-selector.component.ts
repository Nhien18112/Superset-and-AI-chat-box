import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-context-selector',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="context-panel">
      <div class="brand-group">
        <h1>VDT Data Platform</h1>
        <p class="brand-subtitle">AI-Powered & RLS Secured</p>
      </div>
      
      <div class="context-controls">
        <div class="context-group">
          <label>Role</label>
          <select #roleSelect (change)="onRoleChange(roleSelect.value)" class="premium-select">
            <option value="Investor">Investor</option>
            <option value="Broker">Broker</option>
          </select>
        </div>
        <div class="context-group">
          <label>Username (ID)</label>
          <input #userSelect (input)="onUserChange(userSelect.value)" class="premium-input" placeholder="investor_a or broker_1" value="investor_a" />
        </div>
      </div>
    </div>
  `
})
export class ContextSelectorComponent {
  @Output() contextChanged = new EventEmitter<{role: string, username: string}>();

  currentRole = 'Investor';
  currentUsername = 'investor_a';

  onRoleChange(role: string) {
    this.currentRole = role;
    this.emitChange();
  }

  onUserChange(username: string) {
    this.currentUsername = username;
    this.emitChange();
  }

  emitChange() {
    this.contextChanged.emit({ role: this.currentRole, username: this.currentUsername });
  }
}
