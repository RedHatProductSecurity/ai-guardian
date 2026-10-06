use std::env;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let protoc = protoc_bin_vendored::protoc_bin_path()?;
    env::set_var("PROTOC", protoc);

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let proto_dir = manifest_dir.join("../../src/ai_guardian/middleware/openshell/v0_1_2/proto");
    let middleware_proto = proto_dir.join("supervisor_middleware.proto");
    let extension_proto = proto_dir.join("extension.proto");

    println!("cargo:rerun-if-changed={}", middleware_proto.display());
    println!("cargo:rerun-if-changed={}", extension_proto.display());

    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .compile_protos(&[middleware_proto, extension_proto], &[proto_dir])?;
    Ok(())
}
