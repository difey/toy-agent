export function Toast({ visible, message }: { visible: boolean; message: string }) {
  return (
    <div id="toast" className={visible ? 'show' : ''}>
      {message}
    </div>
  );
}
