//! AI Guardian Rust OpenShell middleware binary.

mod service;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    service::run()
}
