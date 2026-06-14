import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-error-toast',
  standalone: true,
  template: `<div class="error-toast">{{ message }}</div>`,
  styles: [
    `.error-toast {
      background-color: #ef4444;
      color: white;
      padding: 10px 20px;
      border-radius: 4px;
      margin: 10px 0;
    }`
  ]
})
export class ErrorToastComponent {
  @Input() message = 'An error occurred';
}
