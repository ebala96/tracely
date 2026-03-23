import ChatInterface from '../components/ChatInterface'

export default function Chat() {
  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="border-b border-gray-100 px-6 py-4">
        <h1 className="text-xl font-bold text-gray-800">Ask Tracely</h1>
        <p className="text-gray-500 text-sm">Query your spending in plain English</p>
      </div>
      <ChatInterface />
    </div>
  )
}
