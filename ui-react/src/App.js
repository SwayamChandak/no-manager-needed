import { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/ui/tabs";
import ChatTab from "./components/ChatTab";
import ApprovalsTab from "./components/ApprovalsTab";

function App() {
  return (
    <div className="min-h-screen bg-background p-4">
      <h1 className="text-2xl font-bold mb-4">E-Commerce Ops Agent</h1>
      <p className="text-muted-foreground mb-6">
        Ask about sales, inventory, marketing, or support issues.
      </p>
      <Tabs defaultValue="chat">
        <TabsList>
          <TabsTrigger value="chat">💬 Chat</TabsTrigger>
          <TabsTrigger value="approvals">⏸ Approvals</TabsTrigger>
        </TabsList>
        <TabsContent value="chat">
          <ChatTab />
        </TabsContent>
        <TabsContent value="approvals">
          <ApprovalsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default App;
