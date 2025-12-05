import { Book } from 'lucide-react';
import { Link } from 'react-router-dom';

export function Header() {
  return (
    <header className="border-b border-border bg-card">
      <div className="container mx-auto px-4 h-14 flex items-center">
        <Link to="/" className="flex items-center gap-2 font-semibold text-foreground hover:text-primary transition-colors">
          <Book className="h-5 w-5" />
          <span>PhotoBook Studio</span>
        </Link>
      </div>
    </header>
  );
}
