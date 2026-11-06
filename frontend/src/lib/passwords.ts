/**
 * The rules a new username and password must meet, checked in the browser so a typo does not cost a
 * round trip. The server checks again, and also refuses the most common passwords and ones that
 * contain the username (core/passwords.py).
 */
export const MIN_PASSWORD = 10;
export const USERNAME = /^[a-z0-9][a-z0-9_.-]{2,31}$/;

/** What a new password still needs, shown under the field while it is typed. */
export function passwordHint(password: string) {
  if (password.length < MIN_PASSWORD) {
    const more = password ? ` (${MIN_PASSWORD - password.length} more)` : '';
    return `At least ${MIN_PASSWORD} characters${more}. A few unrelated words are easy to remember and hard to guess.`;
  }
  return 'Long enough. Avoid anything you use on another site.';
}
